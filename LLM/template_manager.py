import os
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

class TemplateManager:
    """
    Manages custom PowerPoint slide templates (.pptx / .potx) and default design systems.
    """
    def __init__(self, templates_dir=None):
        if templates_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            templates_dir = os.path.join(base_dir, "templates")
        
        self.templates_dir = os.path.abspath(templates_dir)
        os.makedirs(self.templates_dir, exist_ok=True)
        
        # Design system colors
        self.PRIMARY_COLOR = RGBColor(15, 23, 42)     # Dark Slate / Navy (#0F172A)
        self.ACCENT_COLOR = RGBColor(217, 119, 6)     # Amber / Gold (#D97706)
        self.BG_DARK = RGBColor(11, 15, 25)          # Pitch Black / Slate (#0B0F19)
        self.CARD_BG = RGBColor(30, 41, 59)          # Dark Card (#1E293B)
        self.TEXT_LIGHT = RGBColor(248, 250, 252)    # Pure White (#F8FAFC)
        self.TEXT_MUTED = RGBColor(148, 163, 184)    # Slate Muted (#94A3B8)
        self.BORDER_COLOR = RGBColor(51, 65, 85)     # Slate Border (#334155)

    def list_templates(self):
        """Lists available template files in LLM/templates/."""
        if not os.path.exists(self.templates_dir):
            return []
        files = [f for f in os.listdir(self.templates_dir) if f.endswith(('.pptx', '.potx'))]
        return files

    def get_presentation_base(self, template_name=None):
        """Loads a base presentation from a template file, or initializes a standard widescreen deck."""
        if template_name:
            template_path = os.path.join(self.templates_dir, template_name)
            if os.path.exists(template_path):
                return Presentation(template_path)
        
        # Widescreen 16:9 Default Presentation
        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)
        return prs
