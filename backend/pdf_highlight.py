import os
import re
import traceback
import fitz

MISTRAL_GRID_SIZE = 1000.0

# Colors for bounding boxes
COLOR_BBOX_IMG = (0.0, 0.73, 0.83)   # Cyan for Images
COLOR_BBOX_TBL = (0.10, 0.20, 0.90)  # Blue for Tables

def _resolve_bbox_coordinates(bbox_object) -> list | None:
    if bbox_object is None:
        return None

    if hasattr(bbox_object, "top_left_x"):
        try:
            return [
                float(bbox_object.top_left_x),     float(bbox_object.top_left_y),
                float(bbox_object.bottom_right_x), float(bbox_object.bottom_right_y)
            ]
        except (TypeError, ValueError, AttributeError):
            pass

    raw_bbox = getattr(bbox_object, "bbox", None)
    if raw_bbox is None:
        return None

    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        try:
            return [float(c) for c in raw_bbox]
        except (TypeError, ValueError):
            pass

    if hasattr(raw_bbox, "top_left") and hasattr(raw_bbox, "bottom_right"):
        tl, br = raw_bbox.top_left, raw_bbox.bottom_right
        try:
            if hasattr(tl, "x"):
                return [float(tl.x), float(tl.y), float(br.x), float(br.y)]
            if isinstance(tl, (list, tuple)):
                return [float(tl[0]), float(tl[1]), float(br[0]), float(br[1])]
        except (TypeError, ValueError):
            pass

    return None

def highlight_text_in_pdf(
    original_pdf_path: str,
    output_pdf_path:   str,
    extracted_text:    str,
    ocr_response,
) -> str:
    """
    Generates a new PDF report with ONLY bounding box highlights for images and tables.
    The text strip at the bottom is REMOVED as per user request.
    Additionally, crops out the images and saves them to the outputs directory
    so the frontend can display them.
    """
    src_pdf       = fitz.open(original_pdf_path)
    report_pdf    = fitz.open()   
    mistral_pages = getattr(ocr_response, "pages", []) or []

    # Prepare base path for image crops
    output_dir = os.path.dirname(output_pdf_path)
    base_filename = os.path.splitext(os.path.basename(output_pdf_path))[0]

    print(f"[PDF] Generating clean highlighted report: {len(src_pdf)} pages")

    for i, source_page in enumerate(src_pdf):
        try:
            width  = source_page.rect.width
            height = source_page.rect.height
            rot    = source_page.rotation  

            page_data = mistral_pages[i] if i < len(mistral_pages) else None
            page_images = list(getattr(page_data, "images", []) or []) if page_data else []
            page_tables = list(getattr(page_data, "tables", []) or []) if page_data else []

            # Create normal-sized page (no extra height)
            if rot in (90, 270):
                new_page = report_pdf.new_page(width=height, height=width)
            else:
                new_page = report_pdf.new_page(width=width, height=height)

            new_page.set_rotation(rot)
            new_page.show_pdf_page(fitz.Rect(0, 0, width, height), src_pdf, i)

            # Draw IMAGES in Cyan
            for idx, img in enumerate(page_images):
                coords = _resolve_bbox_coordinates(img)
                # Fallback id if none provided
                img_id = getattr(img, "id", None) or f"img-{idx}.jpeg"
                
                if coords:
                    rect = fitz.Rect(
                        coords[0] * width  / MISTRAL_GRID_SIZE, coords[1] * height / MISTRAL_GRID_SIZE,
                        coords[2] * width  / MISTRAL_GRID_SIZE, coords[3] * height / MISTRAL_GRID_SIZE
                    )
                    new_page.draw_rect(rect, color=COLOR_BBOX_IMG, width=2.0)
                    
                    # Draw Label
                    label_text = f"{idx+1} {img_id}"
                    tw = fitz.getTextlength(label_text, fontsize=8)
                    tr = fitz.Rect(rect.x0, rect.y0 - 12, rect.x0 + tw + 6, rect.y0)
                    new_page.draw_rect(tr, color=COLOR_BBOX_IMG, fill=COLOR_BBOX_IMG)
                    new_page.insert_text((rect.x0 + 3, rect.y0 - 3), label_text, fontsize=8, color=(1,1,1))

                    # Crop image visually from original and save it
                    try:
                        # Ensure rect is within page bounds and has positive volume
                        clip_rect = rect & source_page.rect
                        if clip_rect.width > 0 and clip_rect.height > 0:
                            # Use high-res matrix for clear crops
                            mat = fitz.Matrix(2.0, 2.0)
                            pix = source_page.get_pixmap(matrix=mat, clip=clip_rect)
                            img_path = os.path.join(output_dir, f"{base_filename}_{img_id}")
                            if not img_path.endswith('.jpeg') and not img_path.endswith('.jpg'):
                                img_path += '.jpeg'
                            pix.save(img_path)
                    except Exception as e:
                        print(f"[PDF] Could not crop {img_id}: {e}")

            # Draw TABLES in BLUE
            for idx, tbl in enumerate(page_tables):
                coords = _resolve_bbox_coordinates(tbl)
                if coords:
                    rect = fitz.Rect(
                        coords[0] * width  / MISTRAL_GRID_SIZE, coords[1] * height / MISTRAL_GRID_SIZE,
                        coords[2] * width  / MISTRAL_GRID_SIZE, coords[3] * height / MISTRAL_GRID_SIZE
                    )
                    new_page.draw_rect(rect, color=COLOR_BBOX_TBL, width=2.0)

            print(f"[PDF]   Page {i+1} processed successfully.")

        except Exception as page_err:
            print(f"[PDF]   Page {i+1} failed: {page_err}")
            traceback.print_exc()
            try:
                fallback_page = report_pdf.new_page(width=source_page.rect.width, height=source_page.rect.height)
                fallback_page.set_rotation(source_page.rotation)
                fallback_page.show_pdf_page(source_page.rect, src_pdf, i)
            except:
                pass

    report_pdf.save(output_pdf_path)
    report_pdf.close()
    src_pdf.close()

    print(f"[PDF] ✓ Report generated → {output_pdf_path}")
    return output_pdf_path
                fallback_page.set_rotation(source_page.rotation)
                fallback_page.show_pdf_page(source_page.rect, src_pdf, i)
            except:
                pass

    report_pdf.save(output_pdf_path)
    report_pdf.close()
    src_pdf.close()

    print(f"[PDF] ✓ Report generated → {output_pdf_path}")
    return output_pdf_path
