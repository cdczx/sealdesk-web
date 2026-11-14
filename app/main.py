"""SealDesk LAN: local-only document stamping web app."""
from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import pypdfium2 as pdfium

from .engine import DocumentError, info_pdf, read_pdf, stamp_pdf

app = FastAPI(title='SealDesk LAN', docs_url=None, redoc_url=None, openapi_url=None)
security = HTTPBasic(auto_error=False)
BASE = Path(__file__).parent / 'static'
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_PDFS = 12
MAX_BATCH_BYTES = 100 * 1024 * 1024
MAX_IMAGES = 12


def auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    configured_user = os.getenv('SEALDESK_USER', '').strip()
    configured_password = os.getenv('SEALDESK_PASSWORD', '')
    if not configured_user or not configured_password:
        raise HTTPException(503, '请先在 .env 中配置 SEALDESK_USER 和 SEALDESK_PASSWORD。')
    if (credentials is None or
        not secrets.compare_digest(credentials.username.encode(), configured_user.encode()) or
        not secrets.compare_digest(credentials.password.encode(), configured_password.encode())):
        raise HTTPException(401, '需要账户密码', headers={'WWW-Authenticate': 'Basic realm="SealDesk LAN"'})


@app.middleware('http')
async def response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; script-src 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    return response


@app.get('/healthz')
def healthz():
    return {'ok': True}


@app.get('/', response_class=HTMLResponse)
def homepage(_: None = Depends(auth)):
    return (BASE / 'index.html').read_text(encoding='utf-8')


@app.get('/assets/{asset}')
def asset(asset: str, _: None = Depends(auth)):
    if asset not in {'app.js', 'style.css'}:
        raise HTTPException(404)
    media = 'text/javascript' if asset.endswith('.js') else 'text/css'
    return Response((BASE / asset).read_bytes(), media_type=media)


async def limited_file(upload: UploadFile, limit: int) -> bytes:
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise DocumentError(f'文件 {upload.filename or ""} 超过大小限制。')
    return data


def safe_filename(name: str) -> str:
    value = Path((name or 'document.pdf').replace('\\', '/')).name
    value = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', '_', value).strip(' .')
    return value[:100] or 'document.pdf'


@app.post('/api/inspect')
async def inspect(file: UploadFile = File(...), password: str = Form(''), _: None = Depends(auth)):
    try:
        data = await limited_file(file, MAX_PDF_BYTES)
        return info_pdf(data, password)
    except DocumentError as exc:
        raise HTTPException(422, str(exc))


@app.post('/api/render')
async def render(file: UploadFile = File(...), page: int = Form(1),
                 password: str = Form(''), _: None = Depends(auth)):
    try:
        data = await limited_file(file, MAX_PDF_BYTES)
        info = info_pdf(data, password)
        if page < 1 or page > info['pages']:
            raise DocumentError('预览页码超出范围。')
        # PDFium's native renderer is fast and does not flatten the saved PDF.
        pdf = pdfium.PdfDocument(data, password=password or None)
        try:
            p = pdf.get_page(page - 1)
            try:
                w, h = p.get_size()
                scale = min(2, 1250 / max(w, h), 1600000 ** .5 / max(w, h))
                scale = max(0.45, scale)
                bitmap = p.render(scale=scale)
                try:
                    img = bitmap.to_pil().convert('RGB')
                    output = BytesIO()
                    img.save(output, format='PNG', optimize=True)
                    return Response(content=output.getvalue(), media_type='image/png')
                finally:
                    bitmap.close()
            finally:
                p.close()
        finally:
            pdf.close()
    except DocumentError as exc:
        raise HTTPException(422, str(exc))
    except Exception:
        raise HTTPException(422, '无法生成该 PDF 页面预览。')


@app.post('/api/export')
async def export(pdfs: list[UploadFile] = File(...), seals: list[UploadFile] = File(...),
                 settings: str = Form(...), _: None = Depends(auth)):
    try:
        if not 1 <= len(pdfs) <= MAX_PDFS:
            raise DocumentError(f'每批处理 1–{MAX_PDFS} 个 PDF。')
        if not 1 <= len(seals) <= MAX_IMAGES:
            raise DocumentError(f'每批使用 1–{MAX_IMAGES} 个印章图片。')
        try:
            config = json.loads(settings)
            if not isinstance(config, dict):
                raise ValueError()
        except (ValueError, TypeError):
            raise DocumentError('盖章参数格式不正确。')
        images = [await limited_file(f, MAX_IMAGE_BYTES) for f in seals]
        byte_budget = MAX_BATCH_BYTES - sum(len(img) for img in images)
        if byte_budget <= 0:
            raise DocumentError('本次上传文件总量不能超过 100 MB。')
        outputs = []
        for file in pdfs:
            pdfbytes = await limited_file(file, MAX_PDF_BYTES)
            byte_budget -= len(pdfbytes)
            if byte_budget < 0:
                raise DocumentError('本次上传文件总量不能超过 100 MB，请拆分批次。')
            name = safe_filename(file.filename or 'document.pdf')
            if not name.lower().endswith('.pdf'):
                name += '.pdf'
            result = stamp_pdf(pdfbytes, images, config)
            out_name = name[:-4] + '_已盖章.pdf'
            outputs.append((out_name, result))
        if len(outputs) == 1:
            name, payload = outputs[0]
            return Response(content=payload, media_type='application/pdf', headers={
                'Content-Disposition': f"attachment; filename=sealed.pdf; filename*=UTF-8''{quote(name)}"})
        buffer = BytesIO()
        used = set()
        with ZipFile(buffer, mode='w', compression=ZIP_DEFLATED, compresslevel=5) as zipped:
            for index, (name, payload) in enumerate(outputs):
                if name in used:
                    name = f'{index+1:02d}_{name}'
                used.add(name)
                zipped.writestr(name, payload)
        return Response(content=buffer.getvalue(), media_type='application/zip', headers={
            'Content-Disposition': "attachment; filename=sealed-batch.zip"})
    except DocumentError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        # No paths or document contents in the client error response.
        raise HTTPException(422, 'PDF 处理失败。请检查文件内容及盖章配置。') from exc
