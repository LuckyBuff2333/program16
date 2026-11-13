"""以绿色露营插画生成 PPT"""
from pptx import Presentation
from pptx.util import Inches
import os

IMG = r"C:\Users\20637\AppData\Roaming\QoderCN\SharedClientCache\cache\images\31c72ce1\fcp1tf18-58ddbce1.png"

prs = Presentation()
prs.slide_width = Inches(13.33)
prs.slide_height = Inches(7.5)

# 封面：图片铺满
slide = prs.slides.add_slide(prs.slide_layouts[6])
slide.shapes.add_picture(IMG, 0, 0, prs.slide_width, prs.slide_height)

out = os.path.join(os.path.dirname(__file__), "绿色露营封面.pptx")
prs.save(out)
print(f"已生成: {out}")
