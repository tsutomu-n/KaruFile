"""Preserve tagged structure, empty form scaffolding, XMP and soft masks."""
import hashlib
import time

import pikepdf as pq
import pytest

from test_font_replace import font_data, make_pdf
from pdf_shrink import font_replace, font_validate
from pdf_shrink.lossless_jpeg import CandidateRejected


def fixture(tmp_path, mutate):
    source, target, font = (tmp_path / name for name in ('source.pdf', 'target.pdf', 'font.ttf'))
    font.write_bytes(font_data())
    make_pdf(source, mutate=mutate)
    sha = hashlib.sha256(font.read_bytes()).hexdigest()
    return source, target, font, sha


def validate(case):
    source, target, font, sha = case
    return font_validate.validate_candidate(source, target, font_path=font,
        expected_font_sha256=sha, deadline=time.monotonic()+30)


def structure(document, page, font):
    root = document.make_indirect(pq.Dictionary(Type=pq.Name.StructTreeRoot))
    elem = document.make_indirect(pq.Dictionary(Type=pq.Name.StructElem,
        S=pq.Name.P, P=root, Pg=page.obj, K=0, Alt=pq.String('description')))
    root.K = pq.Array([elem])
    root.ParentTree = document.make_indirect(pq.Dictionary(Nums=pq.Array([0, pq.Array([elem])])))
    document.Root.StructTreeRoot = root
    document.Root.MarkInfo = pq.Dictionary(Marked=True)
    page.obj.StructParents = 0
    document.Root.AcroForm = pq.Dictionary(Fields=pq.Array(), DR=pq.Dictionary())
    xmp = document.make_stream(b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:pdf="http://ns.adobe.com/pdf/1.3/" pdf:PDFVersion="1.4"/></rdf:RDF></x:xmpmeta>')
    xmp.Type, xmp.Subtype = pq.Name.Metadata, pq.Name.XML
    document.Root.Metadata = xmp


@pytest.mark.parametrize('tamper', [None, 'tag', 'parent', 'form', 'xmp'])
def test_tagged_empty_form_and_metadata_preserved(tmp_path, tamper):
    case = fixture(tmp_path, structure)
    source, target, font, sha = case
    assert font_replace.preflight(source, font, sha, time.monotonic()+30) == ''
    font_replace.generate(source, target, font, sha, time.monotonic()+30)
    validate(case)
    if tamper is None:
        return
    with pq.open(target) as d:
        if tamper == 'tag': d.Root.StructTreeRoot.K[0].Alt = pq.String('changed')
        elif tamper == 'parent': d.Root.StructTreeRoot.ParentTree.Nums = pq.Array()
        elif tamper == 'form': d.Root.AcroForm.Fields = pq.Array([d.make_indirect(pq.Dictionary(FT=pq.Name.Tx))])
        else: d.Root.Metadata.write(b'<changed/>')
        d.save(tmp_path/'bad.pdf', fix_metadata_version=False)
    with pytest.raises(CandidateRejected):
        validate((source, tmp_path/'bad.pdf', font, sha))


@pytest.mark.parametrize('kind', ['field', 'xfa', 'signature', 'widget'])
def test_active_forms_still_protected(tmp_path, kind):
    def mutate(d, page, font):
        d.Root.AcroForm = pq.Dictionary(Fields=pq.Array())
        if kind == 'field': d.Root.AcroForm.Fields.append(d.make_indirect(pq.Dictionary(FT=pq.Name.Tx)))
        elif kind == 'xfa': d.Root.AcroForm.XFA = d.make_stream(b'x')
        elif kind == 'signature': d.Root.AcroForm.SigFlags = 1
        else: page.Annots = pq.Array([d.make_indirect(pq.Dictionary(Subtype=pq.Name.Widget))])
    source, _, font, sha = fixture(tmp_path, mutate)
    assert font_replace.preflight(source, font, sha, time.monotonic()+30) in {
        'font_replace_forms_or_signatures', 'font_replace_annotations'}


@pytest.mark.parametrize('nested', [False, True])
def test_soft_mask_preserved_and_mutation_detected(tmp_path, nested):
    def mutate(d, page, font):
        image = d.make_stream(bytes(range(27)))
        image.Type, image.Subtype = pq.Name.XObject, pq.Name.Image
        image.Width, image.Height, image.BitsPerComponent = 3, 3, 8
        image.ColorSpace = pq.Name.DeviceRGB
        mask = d.make_stream(bytes(range(9)))
        mask.Type, mask.Subtype = pq.Name.XObject, pq.Name.Image
        mask.Width, mask.Height, mask.BitsPerComponent = 3, 3, 8
        mask.ColorSpace = pq.Name.DeviceGray
        image.SMask = mask
        if nested: mask.SMask = mask
        page.Resources.XObject = pq.Dictionary(I1=image)
    case = fixture(tmp_path, mutate)
    source, target, font, sha = case
    if nested:
        assert font_replace.preflight(source, font, sha, time.monotonic()+30) == 'font_replace_image_soft_mask'
        return
    font_replace.generate(source, target, font, sha, time.monotonic()+30)
    validate(case)
    with pq.open(target) as d:
        d.pages[0].Resources.XObject.I1.SMask.write(bytes([255]*9))
        d.save(tmp_path/'bad.pdf')
    with pytest.raises(CandidateRejected):
        validate((source, tmp_path/'bad.pdf', font, sha))
