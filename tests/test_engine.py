from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas
from fastapi.testclient import TestClient
import pytest

from app.engine import info_pdf, page_numbers, distribute_pages, stamp_pdf, DocumentError
from app.main import app


def demo_pdf(pages=4, rotated=False):
    data=BytesIO(); can=Canvas(data, pagesize=(595,842))
    for i in range(pages):
        can.setFont('Helvetica',20); can.drawString(55,740,f'Selectable text page {i+1}')
        can.line(25,25,565,25); can.showPage()
    can.save()
    raw=data.getvalue()
    if rotated:
        from pypdf import PdfWriter
        writer=PdfWriter();writer.append(BytesIO(raw));writer.pages[0].rotate(90)
        b=BytesIO();writer.write(b);return b.getvalue()
    return raw


def demo_stamp():
    image=Image.new('RGBA',(400,400),(255,255,255,0))
    draw=ImageDraw.Draw(image)
    draw.ellipse((10,10,390,390),outline=(200,20,30,255),width=18)
    draw.line((30,200,370,200),fill=(200,20,30,255),width=25)
    out=BytesIO();image.save(out,format='PNG');return out.getvalue()


@pytest.fixture
def pdf_data():return demo_pdf()
@pytest.fixture
def image_data():return demo_stamp()


def test_select_and_groups():
    assert page_numbers('custom','1,3-5',8)==[1,3,4,5]
    assert page_numbers('even','',6)==[2,4,6]
    assert sum(len(g) for g in distribute_pages(list(range(1,27)),10))==26
    assert all(len(g)>=2 for g in distribute_pages(list(range(1,27)),10))
    with pytest.raises(DocumentError): page_numbers('custom','1,100',4)


def test_regular_preserves_text(pdf_data,image_data):
    cfg={'stamps':[{'image_index':0,'scope':'all','size_mm':35,'x':.6,'y':.7,'rotation':-5,'opacity':.85,'white_to_alpha':True}]}
    output=stamp_pdf(pdf_data,[image_data],cfg)
    reader=PdfReader(BytesIO(output))
    assert len(reader.pages)==4
    assert 'Selectable text page 1' in reader.pages[0].extract_text()
    assert '/XObject' in reader.pages[0]['/Resources']
    assert len(output)>len(pdf_data)


def test_seam_four_sides_and_rotation(pdf_data,image_data):
    for location in ('left','right','top','bottom'):
        output=stamp_pdf(demo_pdf(7,rotated=True),[image_data],{
            'seam':{'enabled':True,'image_index':0,'position':location,'size_mm':40,'scope':'all','max_pages':4}})
        reader=PdfReader(BytesIO(output));assert len(reader.pages)==7
        assert 'Selectable text page 1' in reader.pages[0].extract_text()
        assert int(reader.pages[0].get('/Rotate',0))==0


def test_output_encryption(pdf_data,image_data):
    payload=stamp_pdf(pdf_data,[image_data],{'stamps':[{'image_index':0,'scope':'last'}],'output_password':'abcXYZ123'})
    reader=PdfReader(BytesIO(payload));assert reader.is_encrypted
    assert reader.decrypt('abcXYZ123')
    assert 'Selectable text page 4' in reader.pages[-1].extract_text()


def test_input_encryption(pdf_data,image_data):
    from pypdf import PdfWriter
    w=PdfWriter();w.append(BytesIO(pdf_data));w.encrypt('readme123')
    b=BytesIO();w.write(b)
    assert info_pdf(b.getvalue(),'readme123')['encrypted']
    with pytest.raises(DocumentError):info_pdf(b.getvalue(),'wrong')
    result=stamp_pdf(b.getvalue(),[image_data],{'input_password':'readme123','stamps':[{'image_index':0,'scope':'first'}]})
    assert not PdfReader(BytesIO(result)).is_encrypted


def test_api_endpoints(pdf_data,image_data,monkeypatch):
    monkeypatch.setenv('SEALDESK_USER','admin')
    monkeypatch.setenv('SEALDESK_PASSWORD','secret-pass')
    client=TestClient(app)
    assert client.get('/').status_code==401
    auth=('admin','secret-pass')
    assert client.get('/',auth=auth).status_code==200
    r=client.post('/api/inspect',files={'file':('doc.pdf',pdf_data,'application/pdf')},auth=auth)
    assert r.status_code==200, r.text
    assert r.json()['pages']==4
    r=client.post('/api/render',files={'file':('doc.pdf',pdf_data,'application/pdf')},data={'page':'2'},auth=auth)
    assert r.status_code==200, r.text
    assert r.content[:8]==b'\x89PNG\r\n\x1a\n'
    config=json.dumps({'stamps':[{'image_index':0,'scope':'last'}]})
    r=client.post('/api/export',files=[('pdfs',('doc.pdf',pdf_data,'application/pdf')),('seals',('stamp.png',image_data,'image/png'))],data={'settings':config},auth=auth)
    assert r.status_code==200,r.text
    assert r.headers['content-type']=='application/pdf'
    assert len(PdfReader(BytesIO(r.content)).pages)==4
    r=client.post('/api/export',files=[('pdfs',('a.pdf',pdf_data,'application/pdf')),('pdfs',('b.pdf',pdf_data,'application/pdf')),('seals',('stamp.png',image_data,'image/png'))],data={'settings':config},auth=auth)
    assert r.status_code==200,r.text
    with ZipFile(BytesIO(r.content)) as z:
        assert len(z.namelist())==2
        assert all(z.read(n).startswith(b'%PDF') for n in z.namelist())
