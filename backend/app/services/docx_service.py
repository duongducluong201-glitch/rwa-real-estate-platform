import datetime
import html
import io
import zipfile
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W_PREFIX = f"{{{W_NS}}}"

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

PROPERTY_KIND_LABELS = {
    "apartment": "Căn hộ cao cấp / Penthouse (Apartment)",
    "land": "Đất nền thương mại / Quy hoạch (Land)",
    "building": "Tòa nhà / Sàn văn phòng thương mại (Building)",
    "villa": "Biệt thự / Khu nghỉ dưỡng (Villa)",
}


def _xml_escape(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _w_paragraph(
    text: str = "",
    *,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    size_half_pt: int = 22,  # 11pt
    color_hex: Optional[str] = None,
    align: Optional[str] = None,  # left | center | right | both
    space_before: int = 0,
    space_after: int = 120,
    style: Optional[str] = None,
    runs: Optional[List[Dict[str, Any]]] = None,
) -> str:
    ppr_parts = []
    if style:
        ppr_parts.append(f'<w:pStyle w:val="{_xml_escape(style)}"/>')
    if align:
        ppr_parts.append(f'<w:jc w:val="{align}"/>')
    ppr_parts.append(f'<w:spacing w:before="{space_before}" w:after="{space_after}" w:line="276" w:lineRule="auto"/>')
    ppr = f"<w:pPr>{''.join(ppr_parts)}</w:pPr>"

    if runs is None:
        runs = [
            {
                "text": text,
                "bold": bold,
                "italic": italic,
                "underline": underline,
                "size": size_half_pt,
                "color": color_hex,
            }
        ]

    run_xmls = []
    for r in runs:
        r_text = str(r.get("text", ""))
        rpr_parts = ['<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>']
        if r.get("bold"):
            rpr_parts.append("<w:b/>")
        if r.get("italic"):
            rpr_parts.append("<w:i/>")
        if r.get("underline"):
            rpr_parts.append('<w:u w:val="single"/>')
        sz = r.get("size", size_half_pt)
        if sz:
            rpr_parts.append(f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>')
        clr = r.get("color", color_hex)
        if clr:
            rpr_parts.append(f'<w:color w:val="{clr}"/>')
        rpr = f"<w:rPr>{''.join(rpr_parts)}</w:rPr>"
        run_xmls.append(f'<w:r>{rpr}<w:t xml:space="preserve">{_xml_escape(r_text)}</w:t></w:r>')

    return f"<w:p>{ppr}{''.join(run_xmls)}</w:p>"


def _w_table(headers: List[str], rows: List[List[str]], col_widths_dxa: Optional[List[int]] = None) -> str:
    num_cols = len(headers) if headers else (len(rows[0]) if rows else 2)
    if not col_widths_dxa:
        total_w = 9360  # ~6.5 inches usable width on A4
        if num_cols == 2:
            col_widths_dxa = [3200, 6160]
        else:
            each = total_w // max(1, num_cols)
            col_widths_dxa = [each] * num_cols

    tbl_grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in col_widths_dxa)
    tbl_pr = (
        "<w:tblPr>"
        '<w:tblW w:w="9360" w:type="dxa"/>'
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>'
        '<w:left w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>'
        '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>'
        '<w:right w:val="single" w:sz="6" w:space="0" w:color="CBD5E1"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
        "</w:tblBorders>"
        "<w:tblCellMar>"
        '<w:top w:w="90" w:type="dxa"/>'
        '<w:left w:w="140" w:type="dxa"/>'
        '<w:bottom w:w="90" w:type="dxa"/>'
        '<w:right w:w="140" w:type="dxa"/>'
        "</w:tblCellMar>"
        "</w:tblPr>"
    )

    tr_xmls = []
    if headers:
        cells = []
        for idx, h_text in enumerate(headers):
            w = col_widths_dxa[idx] if idx < len(col_widths_dxa) else 3000
            cell_p = _w_paragraph(
                h_text,
                bold=True,
                size_half_pt=20,
                color_hex="1E3A5F",
                space_after=40,
            )
            cells.append(
                f"<w:tc><w:tcPr><w:tcW w:w=\"{w}\" w:type=\"dxa\"/>"
                f'<w:shd w:val="clear" w:color="auto" w:fill="EAF2FB"/></w:tcPr>{cell_p}</w:tc>'
            )
        tr_xmls.append(f"<w:tr><w:trPr><w:tblHeader/></w:trPr>{''.join(cells)}</w:tr>")

    for r_idx, row in enumerate(rows):
        cells = []
        fill = "F8FAFC" if r_idx % 2 == 1 else "FFFFFF"
        for idx, cell_text in enumerate(row):
            w = col_widths_dxa[idx] if idx < len(col_widths_dxa) else 3000
            is_label_col = (num_cols == 2 and idx == 0)
            cell_p = _w_paragraph(
                cell_text,
                bold=is_label_col,
                size_half_pt=20,
                color_hex="1E293B" if not is_label_col else "334155",
                space_after=40,
            )
            cells.append(
                f"<w:tc><w:tcPr><w:tcW w:w=\"{w}\" w:type=\"dxa\"/>"
                f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/></w:tcPr>{cell_p}</w:tc>'
            )
        tr_xmls.append(f"<w:tr>{''.join(cells)}</w:tr>")

    return f"<w:tbl>{tbl_pr}<w:tblGrid>{tbl_grid}</w:tblGrid>{''.join(tr_xmls)}</w:tbl>"


def generate_legal_deed_docx(estate_info: Dict[str, Any]) -> bytes:
    """
    Sinh tệp Microsoft Word (.docx) chuẩn Office Open XML cho Hồ sơ Pháp lý Bất động sản RWA.
    Hoàn toàn dùng thư viện chuẩn Python (zipfile), mở mượt trên Microsoft Word, Google Docs & LibreOffice.
    """
    name = str(estate_info.get("name") or "Bất động sản RWA")
    symbol = str(estate_info.get("symbol") or "RWA").upper()
    address_text = str(estate_info.get("address_text") or "TP. Hồ Chí Minh, Việt Nam")
    area_m2 = float(estate_info.get("area_m2") or 0)
    property_kind = str(estate_info.get("property_kind") or "apartment")
    kind_label = PROPERTY_KIND_LABELS.get(property_kind, property_kind)
    build_year = estate_info.get("build_year") or 2024
    description = str(
        estate_info.get("description")
        or "Tài sản bất động sản thực tế được thẩm định độc lập và chuẩn hóa hồ sơ pháp lý trên hệ thống RWA Tokenization."
    )
    valuation = float(estate_info.get("valuation") or 0)
    total_shares = float(estate_info.get("total_shares") or 0)
    intrinsic_price = (valuation / total_shares) if total_shares > 0 else 0.0
    doc_cid = str(estate_info.get("doc_cid") or f"QmRWALab{symbol}LegalDeed2026")
    token_address = str(estate_info.get("token_address") or "Chưa phát hành (Sẵn sàng Tokenize - UC-05)")
    issuer_name = str(estate_info.get("issuer_name") or "Đơn vị phát hành (Issuer)")
    issuer_address = str(estate_info.get("issuer_address") or "0x70997970C51812dc3A010C7d01b50e0d17dc79C8")
    created_at = str(estate_info.get("created_at") or datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    doc_number = f"RWA-DEED-{symbol}-2026"

    body_parts = [
        _w_paragraph(
            "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
            bold=True,
            size_half_pt=24,
            color_hex="1E293B",
            align="center",
            space_after=40,
        ),
        _w_paragraph(
            "Độc lập – Tự do – Hạnh phúc",
            bold=True,
            underline=True,
            size_half_pt=22,
            color_hex="334155",
            align="center",
            space_after=180,
        ),
        _w_paragraph(
            "HỒ SƠ PHÁP LÝ BẤT ĐỘNG SẢN & CHỨNG THƯ TOKEN HÓA (RWA)",
            bold=True,
            size_half_pt=30,
            color_hex="1D4ED8",
            align="center",
            style="Title",
            space_before=60,
            space_after=60,
        ),
        _w_paragraph(
            f"Số hiệu hồ sơ: {doc_number}   |   Mã Token (Symbol): {symbol}   |   Phiên bản: v1.0 (IPFS Sealed)",
            italic=True,
            size_half_pt=20,
            color_hex="475569",
            align="center",
            space_after=220,
        ),
        # Mục 1
        _w_paragraph(
            "I. THÔNG TIN PHÁP LÝ & NHẬN DIỆN TÀI SẢN BẤT ĐỘNG SẢN",
            bold=True,
            size_half_pt=24,
            color_hex="1E3A5F",
            style="Heading1",
            space_before=120,
            space_after=100,
        ),
        _w_table(
            ["Hạng mục thông tin", "Chi tiết hồ sơ pháp lý"],
            [
                ["Tên dự án / Bất động sản", name],
                ["Mã cổ phần Token (Symbol)", symbol],
                ["Loại hình bất động sản", kind_label],
                ["Địa chỉ pháp lý thực tế", address_text],
                ["Diện tích sử dụng / đất", f"{area_m2:,.2f} m²"],
                ["Năm hoàn thành / xây dựng", str(build_year)],
                ["Số Giấy CN QSDĐ (Mô phỏng)", f"CS-{symbol}-2026-VN / Sở TN&MT (Bản lưu Lab)"],
                ["Đơn vị phát hành (Issuer)", f"{issuer_name} ({issuer_address})"],
                ["Hợp đồng AssetToken (ERC-20)", token_address],
                ["Mã định danh IPFS (docCID)", doc_cid],
                ["Thời điểm lập hồ sơ", created_at],
            ],
        ),
        # Mục 2
        _w_paragraph(
            "II. THÔNG SỐ ĐỊNH GIÁ & CẤU TRÚC PHÂN MẢNH CỔ PHẦN (TOKENOMICS)",
            bold=True,
            size_half_pt=24,
            color_hex="1E3A5F",
            style="Heading1",
            space_before=220,
            space_after=100,
        ),
        _w_table(
            ["Chỉ tiêu định giá & phân mảnh", "Giá trị ghi nhận"],
            [
                ["Tổng định giá thẩm định ban đầu", f"${valuation:,.2f} MockUSDC"],
                ["Tổng số phần sở hữu phát hành", f"{total_shares:,.0f} {symbol}"],
                ["Giá trị nội tại mỗi phần sở hữu", f"${intrinsic_price:,.2f} MockUSDC / {symbol}"],
                ["Chuẩn hợp đồng thông minh", "ERC-20 Permissioned RWA (AssetToken.sol)"],
                ["Mạng Blockchain triển khai", "Local EVM Anvil (Chain ID: 31337)"],
                ["Cơ chế kiểm soát tuân thủ", "IdentityRegistry (KYC Whitelist), Freeze, Pausable & ForcedTransfer"],
            ],
        ),
        # Mục 3
        _w_paragraph(
            "III. MÔ TẢ CHI TIẾT HIỆN TRẠNG & TÌNH TRẠNG PHÁP LÝ",
            bold=True,
            size_half_pt=24,
            color_hex="1E3A5F",
            style="Heading1",
            space_before=220,
            space_after=80,
        ),
        _w_paragraph(
            description,
            size_half_pt=22,
            color_hex="1E293B",
            align="both",
            space_after=120,
        ),
        _w_paragraph(
            "1. Tình trạng quy hoạch & sở hữu: Tài sản không có tranh chấp, không thuộc diện kê biên bảo đảm thi hành án, đã được Đơn vị phát hành (Issuer) cung cấp đầy đủ hồ sơ thẩm định giá độc lập trước khi niêm yết mở bán sơ cấp qua hợp đồng PrimarySale.",
            size_half_pt=21,
            color_hex="1E293B",
            align="both",
            space_after=80,
        ),
        _w_paragraph(
            "2. Bảo chứng tính toàn vẹn mật mã (IPFS + Keccak-256): Nội dung tệp Word (.docx) này được lưu trữ trên kho IPFS với định danh docCID và đối chiếu mã băm mật mã Keccak-256 (docHash) bất biến trên Smart Contract AssetToken. Bất kỳ sự chỉnh sửa trái phép nào đối với tệp tài liệu đều bị phát hiện ngay lập tức qua chức năng On-chain Verify.",
            size_half_pt=21,
            color_hex="1E293B",
            align="both",
            space_after=80,
        ),
        _w_paragraph(
            "3. Quyền lợi & hạn chế giao dịch nhà đầu tư: Chỉ các địa chỉ ví đã hoàn tất xác minh danh tính KYC (isVerified == true trên IdentityRegistry) và không bị đóng băng (isFrozen == false) mới được phép nhận, chuyển nhượng hoặc giao dịch phần sở hữu trên sàn thứ cấp Marketplace.",
            size_half_pt=21,
            color_hex="1E293B",
            align="both",
            space_after=160,
        ),
        # Mục 4
        _w_paragraph(
            "IV. XÁC NHẬN & MIỄN TRỪ TRÁCH NHIỆM MÔ PHỎNG",
            bold=True,
            size_half_pt=24,
            color_hex="1E3A5F",
            style="Heading1",
            space_before=120,
            space_after=80,
        ),
        _w_paragraph(
            "LƯU Ý PHÁP LÝ (RWA LAB DEMO): Đây là tài liệu hồ sơ pháp lý mô phỏng phục vụ đồ án nghiên cứu & thử nghiệm hệ thống Token hóa Bất động sản trên mạng Blockchain cục bộ Anvil. Token và tài liệu này không có giá trị pháp lý thay thế Giấy chứng nhận quyền sử dụng đất, quyền sở hữu nhà ở và tài sản khác gắn liền với đất do cơ quan nhà nước có thẩm quyền cấp.",
            italic=True,
            size_half_pt=20,
            color_hex="B45309",
            align="both",
            space_after=200,
        ),
        _w_table(
            ["ĐẠI DIỆN ĐƠN VỊ PHÁT HÀNH (ISSUER)", "BỘ PHẬN TUÂN THỦ & THẨM ĐỊNH (COMPLIANCE)"],
            [
                [
                    f"{issuer_name} — Đã ký xác thực hồ sơ gốc IPFS (CID: {doc_cid})",
                    "Compliance Officer (COMPLIANCE_ROLE) — Đã kiểm duyệt điều kiện tuân thủ KYC/AML",
                ]
            ],
            col_widths_dxa=[4680, 4680],
        ),
    ]

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<w:body>"
        + "".join(body_parts)
        + "<w:sectPr>"
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/>'
        "</w:sectPr>"
        "</w:body>"
        "</w:document>"
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        "</Types>"
    )

    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        "</Relationships>"
    )

    doc_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/>'
        '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/></w:rPr>'
        "</w:style>"
        '<w:style w:type="paragraph" w:styleId="Title">'
        '<w:name w:val="Title"/>'
        '<w:rPr><w:b/><w:sz w:val="30"/><w:color w:val="1D4ED8"/></w:rPr>'
        "</w:style>"
        '<w:style w:type="paragraph" w:styleId="Heading1">'
        '<w:name w:val="heading 1"/>'
        '<w:rPr><w:b/><w:sz w:val="24"/><w:color w:val="1E3A5F"/></w:rPr>'
        "</w:style>"
        "</w:styles>"
    )

    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>Hồ sơ Pháp lý BĐS - {_xml_escape(name)} ({_xml_escape(symbol)})</dc:title>"
        f"<dc:creator>{_xml_escape(issuer_name)}</dc:creator>"
        f"<dc:subject>IPFS RWA Legal Deed ({_xml_escape(doc_cid)})</dc:subject>"
        "</cp:coreProperties>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml.encode("utf-8"))
        zf.writestr("_rels/.rels", root_rels_xml.encode("utf-8"))
        zf.writestr("word/document.xml", document_xml.encode("utf-8"))
        zf.writestr("word/_rels/document.xml.rels", doc_rels_xml.encode("utf-8"))
        zf.writestr("word/styles.xml", styles_xml.encode("utf-8"))
        zf.writestr("docProps/core.xml", core_xml.encode("utf-8"))

    return buf.getvalue()


def is_docx_bytes(raw_bytes: bytes) -> bool:
    if not raw_bytes or len(raw_bytes) < 4 or not raw_bytes.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as zf:
            return "word/document.xml" in zf.namelist()
    except Exception:
        return False


def detect_document_type(raw_bytes: bytes) -> Dict[str, str]:
    """Nhận diện định dạng thật của tệp IPFS (ưu tiên Word .docx)."""
    if is_docx_bytes(raw_bytes):
        return {"format": "docx", "ext": ".docx", "mime": DOCX_MIME_TYPE}
    if raw_bytes.startswith(b"%PDF"):
        return {"format": "pdf", "ext": ".pdf", "mime": "application/pdf"}
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"format": "image", "ext": ".png", "mime": "image/png"}
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return {"format": "image", "ext": ".jpg", "mime": "image/jpeg"}
    if raw_bytes.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return {"format": "doc", "ext": ".doc", "mime": "application/msword"}
    return {"format": "text", "ext": ".txt", "mime": "text/plain; charset=utf-8"}


def _render_paragraph_element(p_el: ET.Element) -> tuple[str, str]:
    ppr = p_el.find(f"{W_PREFIX}pPr")
    style_val = ""
    align_val = ""
    if ppr is not None:
        st = ppr.find(f"{W_PREFIX}pStyle")
        if st is not None:
            style_val = (st.attrib.get(f"{W_PREFIX}val") or "").lower()
        jc = ppr.find(f"{W_PREFIX}jc")
        if jc is not None:
            align_val = (jc.attrib.get(f"{W_PREFIX}val") or "").lower()

    html_runs: List[str] = []
    plain_runs: List[str] = []

    for child in p_el:
        if child.tag == f"{W_PREFIX}r":
            rpr = child.find(f"{W_PREFIX}rPr")
            is_bold = False
            is_italic = False
            is_underline = False
            color_hex = ""
            if rpr is not None:
                is_bold = rpr.find(f"{W_PREFIX}b") is not None
                is_italic = rpr.find(f"{W_PREFIX}i") is not None
                u_el = rpr.find(f"{W_PREFIX}u")
                if u_el is not None and u_el.attrib.get(f"{W_PREFIX}val") != "none":
                    is_underline = True
                clr_el = rpr.find(f"{W_PREFIX}color")
                if clr_el is not None:
                    cval = clr_el.attrib.get(f"{W_PREFIX}val") or ""
                    if len(cval) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in cval):
                        color_hex = f"#{cval}"

            run_chunks: List[str] = []
            for sub in child:
                if sub.tag == f"{W_PREFIX}t" and sub.text:
                    run_chunks.append(html.escape(sub.text))
                    plain_runs.append(sub.text)
                elif sub.tag == f"{W_PREFIX}br":
                    run_chunks.append("<br/>")
                    plain_runs.append("\n")
                elif sub.tag == f"{W_PREFIX}tab":
                    run_chunks.append("&nbsp;&nbsp;&nbsp;&nbsp;")
                    plain_runs.append("\t")

            txt_html = "".join(run_chunks)
            if not txt_html:
                continue
            if is_bold:
                txt_html = f"<strong>{txt_html}</strong>"
            if is_italic:
                txt_html = f"<em>{txt_html}</em>"
            if is_underline:
                txt_html = f'<span style="text-decoration:underline;">{txt_html}</span>'
            if color_hex:
                txt_html = f'<span style="color:{color_hex};">{txt_html}</span>'
            html_runs.append(txt_html)

    inner_html = "".join(html_runs).strip()
    plain_text = "".join(plain_runs).strip()
    if not inner_html:
        return "", ""

    align_css = ""
    if align_val == "center":
        align_css = "text-align:center;"
    elif align_val == "right":
        align_css = "text-align:right;"
    elif align_val in ("both", "justify"):
        align_css = "text-align:justify;"

    if "title" in style_val:
        return (
            f'<h1 style="font-size:19px;font-weight:800;margin:10px 0 8px;{align_css}color:#1d4ed8;line-height:1.35;">{inner_html}</h1>',
            plain_text,
        )
    if "heading1" in style_val or style_val == "1":
        return (
            f'<h2 style="font-size:14.5px;font-weight:700;margin:20px 0 10px;padding-bottom:5px;border-bottom:1.5px solid #e2e8f0;color:#1e3a5f;{align_css}">{inner_html}</h2>',
            plain_text,
        )
    if "heading2" in style_val or "heading3" in style_val:
        return (
            f'<h3 style="font-size:13.5px;font-weight:700;margin:14px 0 6px;color:#1e3a5f;{align_css}">{inner_html}</h3>',
            plain_text,
        )
    return (
        f'<p style="font-size:13px;line-height:1.65;margin:0 0 8px;color:#1e293b;{align_css}">{inner_html}</p>',
        plain_text,
    )


def _render_table_element(tbl_el: ET.Element) -> tuple[str, str]:
    rows_html: List[str] = []
    plain_lines: List[str] = []

    for r_idx, tr in enumerate(tbl_el.findall(f"{W_PREFIX}tr")):
        is_header = tr.find(f"{W_PREFIX}trPr/{W_PREFIX}tblHeader") is not None or r_idx == 0
        cells_html: List[str] = []
        row_plain: List[str] = []
        for tc in tr.findall(f"{W_PREFIX}tc"):
            cell_parts = []
            cell_plain = []
            for p in tc.findall(f"{W_PREFIX}p"):
                p_html, p_txt = _render_paragraph_element(p)
                if p_html:
                    cell_parts.append(p_html)
                if p_txt:
                    cell_plain.append(p_txt)
            cell_inner = "".join(cell_parts) or "&nbsp;"
            row_plain.append(" ".join(cell_plain))
            tag = "th" if is_header else "td"
            bg = "#eaf2fb" if is_header else ("#f8fafc" if r_idx % 2 == 0 else "#ffffff")
            cells_html.append(
                f'<{tag} style="border:1px solid #cbd5e1;padding:7px 11px;background:{bg};vertical-align:top;text-align:left;">{cell_inner}</{tag}>'
            )
        rows_html.append(f"<tr>{''.join(cells_html)}</tr>")
        plain_lines.append(" | ".join(row_plain))

    table_html = (
        '<div style="overflow-x:auto;margin:10px 0 14px;">'
        '<table style="width:100%;border-collapse:collapse;font-size:12.5px;">'
        + "".join(rows_html)
        + "</table></div>"
    )
    return table_html, "\n".join(plain_lines)


def docx_bytes_to_html(raw_bytes: bytes) -> Dict[str, Any]:
    """
    Chuyển đổi tệp Word (.docx) từ bytes sang HTML sạch để hiển thị trực tiếp trên giao diện Web.
    """
    with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as zf:
        xml_bytes = zf.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    body = root.find(f"{W_PREFIX}body")
    if body is None:
        return {
            "format": "docx",
            "html": "<p>Tệp Word không có nội dung hiển thị.</p>",
            "plain_text": "",
            "paragraph_count": 0,
            "table_count": 0,
        }

    blocks_html: List[str] = []
    plain_blocks: List[str] = []
    p_count = 0
    t_count = 0

    for child in body:
        if child.tag == f"{W_PREFIX}p":
            h, txt = _render_paragraph_element(child)
            if h:
                blocks_html.append(h)
                p_count += 1
            if txt:
                plain_blocks.append(txt)
        elif child.tag == f"{W_PREFIX}tbl":
            h, txt = _render_table_element(child)
            blocks_html.append(h)
            plain_blocks.append(txt)
            t_count += 1

    return {
        "format": "docx",
        "html": '<div class="rwa-docx-body">' + "".join(blocks_html) + "</div>",
        "plain_text": "\n".join(plain_blocks),
        "paragraph_count": p_count,
        "table_count": t_count,
    }
