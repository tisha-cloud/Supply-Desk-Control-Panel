import os
import copy
from datetime import datetime
import pptx
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
import lxml.etree as etree


def safe_str(val, default=""):
    """Convert value to clean string, handling nan/None/empty gracefully."""
    if val is None:
        return default
    s = str(val).strip()
    if s.lower() in ('nan', 'none', 'n/a', 'available on request / document image', ''):
        return default
    return s


def format_currency(val, prefix="INR ", suffix=" / Sq. Ft. / Month"):
    """Format a rent/charge value nicely."""
    s = safe_str(val)
    if not s:
        return "Quote on Request"
    # Already formatted
    if 'INR' in s.upper() or 'included' in s.lower() or 'tbd' in s.lower() or 'quote' in s.lower():
        return s
    try:
        num = float(str(s).replace(',', ''))
        return f"{prefix}{num:,.0f}{suffix}"
    except (ValueError, TypeError):
        return s


def format_area(val):
    """Format area value nicely."""
    s = safe_str(val)
    if not s:
        return "Available on Request"
    try:
        num = float(str(s).replace(',', ''))
        if num > 0:
            return f"{num:,.0f} Sq. Ft."
    except (ValueError, TypeError):
        pass
    if 'sq' not in s.lower() and 'sft' not in s.lower():
        return f"{s} Sq. Ft."
    return s


def set_cell_text(cell, text, font_size=Pt(9), bold=False, color=RGBColor(0x33, 0x33, 0x33)):
    """Set cell text with consistent formatting."""
    cell.text = safe_str(text)
    for p in cell.text_frame.paragraphs:
        p.font.name = "Segoe UI"
        p.font.size = font_size
        p.font.bold = bold
        p.font.color.rgb = color


class PPTGenerator:
    def __init__(self, template_name="options format.pptx"):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.template_path = os.path.join(self.base_dir, "templates", template_name)
        if not os.path.exists(self.template_path):
            # Fallback check
            alt_path = os.path.join(self.base_dir, "..", "LLM", "templates", template_name)
            if os.path.exists(alt_path):
                self.template_path = alt_path

    def populate_summary_slide(self, slide9, matched_records):
        """Populates Table 7 on Slide 9 (Location Map / Proposed Options List) with matched options."""
        for shape in slide9.shapes:
            if shape.has_table:
                tbl = shape.table
                first_cell_text = tbl.rows[0].cells[0].text.strip().upper()
                if first_cell_text.startswith("SL") or first_cell_text.startswith("SR") or first_cell_text.startswith("NO"):
                    total_rows = len(tbl.rows) - 1  # data rows (typically 16)
                    for idx in range(total_rows):
                        row_cells = tbl.rows[idx + 1].cells
                        if idx < len(matched_records):
                            rec = matched_records[idx]
                            prop_name = safe_str(rec.get('building_name', rec.get('property_name')), f'Option {idx+1}')
                            loc_name = safe_str(rec.get('micromarket_category', rec.get('address_location')), 'Bangalore')
                            
                            set_cell_text(row_cells[0], str(idx + 1), font_size=Pt(8), bold=True)
                            set_cell_text(row_cells[1], prop_name, font_size=Pt(8), bold=True)
                            if len(row_cells) > 2:
                                set_cell_text(row_cells[2], loc_name, font_size=Pt(8))
                        else:
                            set_cell_text(row_cells[0], "")
                            set_cell_text(row_cells[1], "")
                            if len(row_cells) > 2:
                                set_cell_text(row_cells[2], "")
                    break

    def populate_option_slide(self, slide, rec, opt_num):
        """Populates Slide 10 option template with detailed property information."""
        prop_name = safe_str(rec.get('building_name', rec.get('property_name')), f'Option {opt_num}')
        dev_name = safe_str(rec.get('developer_landlord', rec.get('developer_name')), 'Developer Group')
        loc_name = safe_str(rec.get('address_location', rec.get('micromarket_category')), 'Bangalore')
        mm_name = safe_str(rec.get('micromarket_category'), 'Bangalore')
        
        # 1. Update Header Title — find the shape with "Option" text
        for shape in slide.shapes:
            if shape.has_text_frame:
                txt = shape.text_frame.text.strip()
                if "Option" in txt and ("–" in txt or "-" in txt or txt.startswith("Option")):
                    shape.text_frame.text = f"Option – {opt_num} – {prop_name}"
                    for p in shape.text_frame.paragraphs:
                        p.font.name = "Segoe UI"
                        p.font.size = Pt(20)
                        p.font.bold = True
                        p.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)
                    break

        # 2. Update Tables
        for shape in slide.shapes:
            if shape.has_table:
                tbl = shape.table
                t_first_cell = tbl.rows[0].cells[0].text.strip().upper()
                
                # Table: Developer Info (3 rows x 2 cols)
                if 'NAME OF THE DEVELOPER' in t_first_cell or 'DEVELOPER' in t_first_cell:
                    set_cell_text(tbl.rows[0].cells[1], dev_name, bold=True)
                    set_cell_text(tbl.rows[1].cells[1], safe_str(rec.get('building_structure'), 'Grade A Building'))
                    set_cell_text(tbl.rows[2].cells[1], f"{loc_name}, {mm_name}" if loc_name != mm_name else loc_name)

                # Table: Building Details (4 rows x 2 cols)
                elif 'PROPOSED SPACE' in t_first_cell or 'BUILDING DETAIL' in t_first_cell:
                    if len(tbl.rows) >= 4:
                        set_cell_text(tbl.rows[1].cells[1], safe_str(rec.get('building_structure'), 'G + Upper Floors'))
                        set_cell_text(tbl.rows[2].cells[1], safe_str(rec.get('average_floor_plate_sqft'), 'Flexible floor plates'))
                        set_cell_text(tbl.rows[3].cells[1], safe_str(rec.get('floor_plate_efficiency'), '75-80%'))

                # Table: Commercial Details (9 rows x 2 cols)
                elif 'COMMERCIAL' in t_first_cell:
                    rent = format_currency(rec.get('quoted_rental_sqft_pm'))
                    cam = safe_str(rec.get('cam_charges_sqft_pm'), 'At Actuals')
                    if cam and 'INR' not in cam.upper() and cam not in ('At Actuals', 'Included in rent', 'TBD'):
                        try:
                            cam_num = float(cam.replace(',', ''))
                            cam = f"INR {cam_num:,.0f} / Sq. Ft. / Month"
                        except (ValueError, TypeError):
                            pass
                    parking_chg = safe_str(rec.get('car_parking_charges'), 'Included')
                    if parking_chg and 'INR' not in parking_chg.upper() and parking_chg != 'Included':
                        try:
                            pk_num = float(parking_chg.replace(',', '').replace('INR', '').strip())
                            parking_chg = f"INR {pk_num:,.0f} / Slot / Month"
                        except (ValueError, TypeError):
                            pass
                    
                    esc = safe_str(rec.get('rental_escalation'), '15% Every 36 Months')
                    sec_dep = safe_str(rec.get('security_deposit_months'), '6 Months')
                    lease_term = safe_str(rec.get('lease_tenure_months'), '60 Months')
                    lock_in = safe_str(rec.get('lock_in_period_months'), '36 Months')
                    notice = safe_str(rec.get('notice_period_months'), '6 Months')
                    
                    # Ensure "Months" suffix
                    for val_ref in [sec_dep, lease_term, lock_in, notice]:
                        if val_ref and val_ref.isdigit():
                            val_ref = f"{val_ref} Months"

                    rows_data = [
                        (1, rent, True),
                        (2, cam, False),
                        (3, parking_chg, False),
                        (4, esc, False),
                        (5, sec_dep, False),
                        (6, lease_term, False),
                        (7, lock_in, False),
                        (8, notice, False),
                    ]
                    for row_idx, val, is_bold in rows_data:
                        if row_idx < len(tbl.rows):
                            set_cell_text(tbl.rows[row_idx].cells[1], val, bold=is_bold)

                # Table: Details of Space Offered (8 rows x 2 cols)
                elif 'DETAILS OF THE SPACE' in t_first_cell or 'SPACE OFFERED' in t_first_cell:
                    area = format_area(rec.get('available_inventory_sqft'))
                    floor = safe_str(rec.get('floor_offered'), 'Multiple Floors')
                    fitout = safe_str(rec.get('fitout_details', rec.get('status')), 'Furnished')
                    power = safe_str(rec.get('power_kva'), '1 KVA / 100 Sq. Ft.')
                    power_bk = safe_str(rec.get('power_backup'), '100% DG Back-up')
                    parking_rat = safe_str(rec.get('car_parking_ratio'), '1:1000 Sq. Ft.')
                    timeline = safe_str(rec.get('timeline', rec.get('status')), 'Immediate')

                    rows_data = [
                        (1, area, True),
                        (2, floor, False),
                        (3, fitout, False),
                        (4, power, False),
                        (5, power_bk, False),
                        (6, parking_rat, False),
                        (7, timeline, False),
                    ]
                    for row_idx, val, is_bold in rows_data:
                        if row_idx < len(tbl.rows):
                            set_cell_text(tbl.rows[row_idx].cells[1], val, bold=is_bold)

        # 3. Update Highlights Box
        for shape in slide.shapes:
            if shape.has_text_frame:
                txt_lower = shape.text_frame.text.lower()
                if any(kw in txt_lower for kw in ["approvals", "distance", "eateries", "highlights", "nearby"]):
                    tf = shape.text_frame
                    tf.text = ""
                    
                    highlights = [
                        f"• Occupancy Certificate: {safe_str(rec.get('occupancy_certificate'), 'Yes')}",
                        f"• Address: {safe_str(rec.get('address_location'), loc_name)}",
                        f"• Micromarket: {mm_name}",
                        f"• Developer: {dev_name}",
                    ]
                    
                    contact = safe_str(rec.get('contact_person'))
                    if contact:
                        highlights.append(f"• Contact: {contact}")
                    email = safe_str(rec.get('official_email'))
                    if email:
                        highlights.append(f"• Email: {email}")
                    phone = safe_str(rec.get('contact_number'))
                    if phone:
                        highlights.append(f"• Phone: {phone}")
                    
                    loc_map = safe_str(rec.get('location_map'))
                    if loc_map and 'maps.google' not in loc_map:
                        highlights.append(f"• Location: {loc_map}")
                    
                    for idx, h_text in enumerate(highlights):
                        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
                        p.text = h_text
                        p.font.name = "Segoe UI"
                        p.font.size = Pt(10)
                        p.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
                        p.space_after = Pt(4)
                    break

    def _deep_clone_slide(self, prs, template_slide):
        """
        Deep-clones a slide, preserving shapes, tables, images and formatting.

        Two things here are easy to get wrong and both silently ruin the deck:

        1. The background must be copied as the `<p:bg>` child only. python-pptx's
           `slide.background._element` is the whole `<p:cSld>`, which *contains*
           the shape tree - replacing it swaps the freshly cloned shapes back for
           the template's, so every option slide ends up showing option 1.
        2. Relationships must be carried across under their original rIds. The
           copied `<a:blip r:embed="rId3">` still points at rId3, and if the new
           slide part has no such relationship the picture resolves to nothing.
        """
        layout = template_slide.slide_layout
        new_slide = prs.slides.add_slide(layout)

        # Drop the layout's placeholder shapes; the clone brings its own.
        for sp in list(new_slide.shapes):
            sp.element.getparent().remove(sp.element)

        for shape_el in template_slide.shapes._spTree:
            tag = etree.QName(shape_el.tag).localname if isinstance(shape_el.tag, str) else ''
            if tag in ('sp', 'pic', 'graphicFrame', 'grpSp', 'cxnSp'):
                new_slide.shapes._spTree.append(copy.deepcopy(shape_el))

        # Carry image and media relationships over, keeping each rId identical so
        # the copied r:embed references still resolve.
        for rId, rel in template_slide.part.rels.items():
            if rel.reltype.endswith("slideLayout"):
                continue  # add_slide already wired the layout
            if rId in new_slide.part.rels:
                continue
            try:
                if rel.is_external:
                    new_slide.part.rels._add_relationship(rel.reltype, rel.target_ref, rId, True)
                else:
                    new_slide.part.rels._add_relationship(rel.reltype, rel.target_part, rId, False)
            except Exception:
                pass

        # Copy only the background element, never the containing cSld.
        try:
            ns = 'http://schemas.openxmlformats.org/presentationml/2006/main'
            src_cSld = template_slide._element.find('{%s}cSld' % ns)
            dst_cSld = new_slide._element.find('{%s}cSld' % ns)
            if src_cSld is not None and dst_cSld is not None:
                src_bg = src_cSld.find('{%s}bg' % ns)
                old_bg = dst_cSld.find('{%s}bg' % ns)
                if old_bg is not None:
                    dst_cSld.remove(old_bg)
                if src_bg is not None:
                    dst_cSld.insert(0, copy.deepcopy(src_bg))
        except Exception:
            pass

        return new_slide

    def generate_presentation(self, matched_records, summary_data=None, client_name="Valued Client", 
                              requirement_summary="Office Space Requirement", output_filename="Commercial_Options_Deck.pptx"):
        """
        Loads 'options format.pptx', preserves slides 1-8 unchanged, populates summary slide 9,
        populates option slides from slide 10 onwards, and moves closing slides 11-13 to the end.
        """
        prs = pptx.Presentation(self.template_path)
        
        output_dir = os.path.join(self.base_dir, "generated_decks")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        if not matched_records:
            matched_records = [{
                'building_name': 'Sample Commercial Property',
                'developer_landlord': 'Prime Developer Group',
                'micromarket_category': 'Bangalore',
                'available_inventory_sqft': '15,000',
                'quoted_rental_sqft_pm': '100'
            }]

        num_options = min(len(matched_records), 16)  # Max 16 options fit on Slide 9 table

        # Step 1: Populate Slide 9 (Summary Table)
        slide9 = prs.slides[8]
        self.populate_summary_slide(slide9, matched_records[:num_options])

        # Step 2: Populate Slide 10 (Option 1 template)
        slide10_template = prs.slides[9]
        self.populate_option_slide(slide10_template, matched_records[0], 1)

        # Store closing slide IDs (Slides 11, 12, 13 = indices 10, 11, 12)
        sld_id_list = list(prs.slides._sldIdLst)
        closing_sld_ids = sld_id_list[10:13] if len(sld_id_list) > 12 else []

        # Clone Slide 10 for Options 2..N
        for idx in range(2, num_options + 1):
            new_slide = self._deep_clone_slide(prs, slide10_template)
            self.populate_option_slide(new_slide, matched_records[idx - 1], idx)

        # Step 3: Reorder closing slides (Why BangaloreOffice, Contact, Thank You) to the very end
        for sld_id_el in closing_sld_ids:
            prs.slides._sldIdLst.remove(sld_id_el)
            prs.slides._sldIdLst.append(sld_id_el)

        prs.save(output_path)
        print(f"   -> Generated presentation deck at: {output_path}")
        return output_path
