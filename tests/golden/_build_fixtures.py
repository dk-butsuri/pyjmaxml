"""Build golden-test fixture XMLs from JMA samples / live messages (one-off research script)."""
import copy, shutil
from pathlib import Path
from lxml import etree

OUT = Path(__file__).resolve().parent  # tests/golden
J = "http://xml.kishou.go.jp/jmaxml1/"
IB = "http://xml.kishou.go.jp/jmaxml1/informationBasis1/"
B = "http://xml.kishou.go.jp/jmaxml1/body/meteorology1/"
NS = {"j": J, "ib": IB, "b": B}

def load(p): return etree.parse(p)
def save(t, rel):
    p = OUT / rel; p.parent.mkdir(parents=True, exist_ok=True)
    t.write(str(p), xml_declaration=True, encoding="UTF-8")
def settext(t, path, v): t.find(path, NS).text = v

def head(t, cdt=None, rdt=None, status=None, infotype=None):
    if cdt: settext(t, "j:Control/j:DateTime", cdt)
    if status: settext(t, "j:Control/j:Status", status)
    if rdt:
        settext(t, "ib:Head/ib:ReportDateTime", rdt)
        settext(t, "ib:Head/ib:TargetDateTime", rdt)
    if infotype: settext(t, "ib:Head/ib:InfoType", infotype)

def city_kind(t, city, kinds):
    """Replace Kind elements of Warning[市町村等]/Item for `city`. kinds: list of (name, code, status)."""
    for w in t.findall(".//b:Warning", NS):
        if "（市町村等）" not in w.get("type"): continue
        for it in w.findall("b:Item", NS):
            if it.findtext("b:Area/b:Code", namespaces=NS) != city: continue
            for k in it.findall("b:Kind", NS): it.remove(k)
            for i, (n, c, s) in enumerate(kinds):
                k = etree.Element(f"{{{B}}}Kind")
                if n is not None: etree.SubElement(k, f"{{{B}}}Name").text = n
                if c is not None: etree.SubElement(k, f"{{{B}}}Code").text = c
                etree.SubElement(k, f"{{{B}}}Status").text = s
                it.insert(i, k)
            return
    raise KeyError(city)

def flood_kind(t, name, code, cond):
    n = 0
    for k in list(t.iterfind(".//ib:Headline/ib:Information/ib:Item/ib:Kind", NS)) + \
             [k for k in t.iterfind(".//b:Warning/b:Item/b:Kind", NS) if k.find("b:Code", NS) is not None and k.findtext("b:Name", namespaces=NS) != "浸水想定地区"]:
        p = "ib:" if k.tag.startswith(f"{{{IB}}}") else "b:"
        k.find(p + "Name", NS).text = name
        k.find(p + "Code", NS).text = code
        c = k.find(p + "Condition", NS)
        if c is not None: c.text = cond
        n += 1
    assert n, "no flood kinds"

S = Path("samples"); L = Path("live")
A = S / "15_16_03_241226_VPWW55.xml"
WS = L / "20261111150121_0_VPWS50_010000.xml"
W61 = L / "20261111122220_0_VPWW61_460100.xml"
F1 = S / "16_08_01_260312_VXKOii.xml"
S1 = S / "91_01_01_241031_VXSUii.xml"

# shared (unmodified)
shutil.copy(A, OUT / "_shared/vpww55_wakkanai_20200622T2300.xml")
shutil.copy(WS, OUT / "_shared/vpws50_20261112T0000.xml")
shutil.copy(W61, OUT / "_shared/vpww61_kagoshima_20261111T2122.xml")
shutil.copy(F1, OUT / "_shared/vxko_oyabe_l2.xml")
shutil.copy(S1, OUT / "_shared/vxsu_8201813100_l2.xml")
shutil.copy(S / "15_15_01_220314_VPWW54.xml", OUT / "_shared/vpww54_h27.xml")
shutil.copy(next(S.glob("*VPWP50*.xml")), OUT / "_shared/vpwp50.xml")

# A' : 1h later, 稚内市 L4 -> L3
t = load(A); head(t, cdt="2020-06-22T15:00:00Z", rdt="2020-06-23T00:00:00+09:00")
city_kind(t, "0121400", [("レベル３大雨警報", "03", "危険警報から警報")]); save(t, "_shared/vpww55_wakkanai_20200623T0000_downgrade.xml")
# A'' : 2h later, 稚内市 cleared
t = load(A); head(t, cdt="2020-06-22T16:00:00Z", rdt="2020-06-23T01:00:00+09:00")
city_kind(t, "0121400", [("レベル３大雨警報", "03", "解除")]); save(t, "g01_issue_switch_clear/03.xml")
# correction: same RDT, newer Control/DateTime, 猿払村 L3 -> L2
t = load(A); head(t, cdt="2020-06-22T14:05:00Z", infotype="訂正")
city_kind(t, "0151100", [("レベル２大雨注意報", "10", "警報から注意報")]); save(t, "g02_correction/02.xml")
# training / test
for st, fn in (("訓練", "02.xml"), ("試験", "03.xml")):
    t = load(A); head(t, cdt="2020-06-22T15:00:00Z", rdt="2020-06-23T00:00:00+09:00", status=st)
    city_kind(t, "0121400", [("レベル５大雨特別警報", "33", "発表")]); save(t, "g03_training_and_test/" + fn)
# watermark: VPWW61 issued after the VPWS50 snapshot
t = load(W61); head(t, cdt="2026-11-11T15:05:00Z", rdt="2026-11-12T00:05:00+09:00")
city_kind(t, "4620100", [("乾燥注意報", "21", "発表")]); save(t, "g06c_vpws50_watermark/01.xml")
# VXKO upgrade and cancel
t = load(F1); head(t, cdt="2025-08-06T22:40:00Z", rdt="2025-08-07T07:40:00+09:00")
flood_kind(t, "レベル３氾濫警報", "30", "レベル３氾濫警報（発表）"); save(t, "g08_vxko_upgrade_cancel/02.xml")
t = load(F1); head(t, cdt="2025-08-06T23:40:00Z", rdt="2025-08-07T08:40:00+09:00", infotype="取消")
save(t, "g08_vxko_upgrade_cancel/03.xml")
# VXSU release
t = load(S1); head(t, cdt="2023-07-10T08:35:30Z", rdt="2023-07-10T17:35:00+09:00")
flood_kind(t, "レベル２氾濫注意報解除", "10", "レベル２氾濫注意報解除"); save(t, "g09_vxsu_release/02.xml")
print("ok")
