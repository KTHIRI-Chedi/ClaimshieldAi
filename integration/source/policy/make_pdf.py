import sys; sys.path.insert(0,'.')
from motor_policy_wording import TITLE,SUBTITLE,VERSION,PARTS
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import cm
pdfmetrics.registerFont(TTFont('DV','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DVB','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
ss=getSampleStyleSheet()
H=ParagraphStyle('h',fontName='DVB',fontSize=16,leading=20,spaceAfter=6)
S=ParagraphStyle('s',fontName='DV',fontSize=9,leading=12,textColor='#555555')
P=ParagraphStyle('p',fontName='DVB',fontSize=12.5,leading=16,spaceBefore=12,spaceAfter=4)
C=ParagraphStyle('c',fontName='DVB',fontSize=10,leading=13,spaceBefore=6)
B=ParagraphStyle('b',fontName='DV',fontSize=9.5,leading=13,spaceAfter=3)
st=[Paragraph(TITLE,H),Paragraph(SUBTITLE,S),Paragraph(VERSION,S),Spacer(1,8)]
for part,_,clauses in PARTS:
    st.append(Paragraph(part,P))
    for cid,title,body in clauses:
        st.append(Paragraph(f"{cid} - {title}",C)); st.append(Paragraph(body,B))
def foot(c,d):
    c.setFont('DV',8); c.drawString(2*cm,1.2*cm,"ClaimShield Mutual - fictional policy wording MW-2026.1"); c.drawRightString(19*cm,1.2*cm,f"Page {d.page}")
SimpleDocTemplate('Motor-Policy-Wording.pdf',pagesize=A4,leftMargin=2*cm,rightMargin=2*cm,topMargin=2*cm,bottomMargin=2*cm,title=TITLE).build(st,onFirstPage=foot,onLaterPages=foot)
with open('Motor-Policy-Wording.md','w') as f:
    f.write(f"# {TITLE}\n\n_{SUBTITLE}_\n\n{VERSION}\n")
    for part,_,cl in PARTS:
        f.write(f"\n## {part}\n")
        for cid,t,b in cl: f.write(f"\n**{cid} - {t}**\n{b}\n")
