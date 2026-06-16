"""Generate 30 synthetic aircraft reports across 3 types (10 each).

Types:
  - Maintenance Inspection Report (MIR)
  - Flight Test Report (FTR)
  - Service Bulletin (SB)

Run once to populate documents/ + manifest.json. Deterministic via fixed seed.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(42)

HERE = Path(__file__).resolve().parent
DOCS = HERE / "documents"

AIRCRAFT_FLEET = [
    ("Airbus A320-200",   "VT-IDA", "CFM56-5B4/P",   "Indigo"),
    ("Airbus A320neo",    "VT-EXP", "PW1127G-JM",    "Indigo"),
    ("Airbus A321neo",    "VT-IUR", "CFM LEAP-1A26", "Vistara"),
    ("Airbus A330-300",   "VT-JFK", "RR Trent 772B", "Air India"),
    ("Airbus A350-900",   "VT-JRC", "RR Trent XWB",  "Air India"),
    ("Boeing 737-800",    "VT-SGE", "CFM56-7B26",    "SpiceJet"),
    ("Boeing 737 MAX 8",  "VT-AKO", "CFM LEAP-1B27", "Akasa Air"),
    ("Boeing 777-300ER",  "VT-ALR", "GE90-115BL",    "Air India"),
    ("Boeing 787-8",      "VT-ANI", "GEnx-1B70",     "Air India"),
    ("ATR 72-600",        "VT-IRR", "PW127M",        "IndiaOne Air"),
    ("Embraer E190",      "VT-JCD", "CF34-10E",      "Star Air"),
    ("De Havilland DHC-6","VT-RDA", "PT6A-34",       "Fly91"),
]

INSPECTORS = [
    "S. Krishnamurthy, AME L1", "Anjali Mehta, AME L2", "R. Venkatesan, AME L1",
    "Priya Sharma, B1.1", "Arjun Kapoor, B2", "Meera Iyer, AME L2",
    "Vikram Nair, AME L1", "Karthik Raghunathan, B1.3",
]

TEST_PILOTS = [
    "Capt. R. Subramanian", "Capt. P. Bhattacharya", "Capt. A. Deshmukh",
    "Capt. S. Mukherjee", "Capt. V. Ramachandran", "Capt. M. Choudhary",
]

ENGINEERS = [
    "Dr. K. Raghavan, Lead Engineer", "Prof. S. Iyer, Chief Engineer",
    "A. Vasudevan, Senior Engineer", "P. Krishnan, Design Engineer",
    "T. Balakrishnan, Test Engineer",
]


# ---------------------------------------------------------------------------
# Maintenance Inspection Reports — 10
# ---------------------------------------------------------------------------

ATA_CHAPTERS = [
    ("21", "Air Conditioning"),
    ("24", "Electrical Power"),
    ("27", "Flight Controls"),
    ("28", "Fuel System"),
    ("29", "Hydraulic Power"),
    ("32", "Landing Gear"),
    ("34", "Navigation"),
    ("36", "Pneumatic"),
    ("49", "Airborne Auxiliary Power"),
    ("71", "Power Plant"),
    ("72", "Engine"),
    ("75", "Engine Air"),
    ("78", "Engine Exhaust"),
]

CHECK_LEVELS = ["A-Check", "B-Check", "C-Check", "Phase-1", "Phase-2", "Daily Pre-flight"]

MIR_FINDINGS = [
    "Leading edge slat actuator showing minor hydraulic seepage within AMM limits.",
    "Forward galley chiller coolant level below MIN mark, replenished.",
    "L1 wheel brake assembly worn to 28% remaining; replacement scheduled.",
    "APU oil consumption rate elevated to 0.18 L/hr; trend monitoring continued.",
    "Lavatory waste tank flush motor intermittent; cleaned and tested OK.",
    "Right main landing gear oleo strut servicing low pressure, recharged to spec.",
    "FADEC software version mismatch found, software update SB-FADEC-22 applied.",
    "Engine #2 IDG oil filter delta-P approaching caution band, filter replaced.",
    "Cabin pressurization outflow valve actuator response time 1.2s, within limit.",
    "Static port heater P/N 387-2241-04 failed BIT, replaced with new unit.",
]

MIR_ACTIONS = [
    "Component replaced per IPC reference; functional test PASSED.",
    "Adjusted to manufacturer specification; recorded in tech log.",
    "Deferred to next scheduled inspection per MEL Cat-B (10 days).",
    "Cleared after re-inspection; no further action required.",
    "Lubrication performed per MM 12-21-04; signed off.",
    "Borescope inspection scheduled for next A-Check.",
]

# Prose narrative blocks for MIR — written the way an AME actually writes notes
MIR_NARRATIVES = [
    "During the scheduled inspection the crew reported a mild buffet on rotation, observed "
    "intermittently over the last three sectors. Initial walk-around revealed a small area of "
    "paint blistering on the left wing fairing, approximately 40 mm in diameter, with no "
    "underlying structural deformation evident. Tap-testing of the surrounding skin produced "
    "no anomalies, and dye-penetrant inspection of the adjacent fasteners returned negative. "
    "The aircraft was returned to service with continued monitoring; a follow-up borescope "
    "inspection is recommended at the next opportunity not later than 250 flight hours.",

    "An oil weeping was noted at the No. 2 engine accessory gearbox drive seal, estimated at "
    "approximately 6 ml of accumulated residue since the previous A-check. No corresponding "
    "oil quantity loss was reflected in trend data, and the drain mast remained dry. The seal "
    "is at 88% of its expected service life and is being monitored under engineering surveillance. "
    "Recommend deferred replacement at the next available C-check unless trend changes.",

    "The pilot's defect entry referenced a momentary EICAS message during cruise on flight "
    "VT-EXP-2024-118. The FDR data was reviewed; the message lasted 0.4 seconds and was "
    "consistent with a known transient on the bleed pressure regulator under low-power "
    "conditions at high altitude. The current population of this regulator is being tracked "
    "under engineering bulletin EB-36-014. No corrective action required at this inspection.",

    "Routine inspection of the main landing gear assembly revealed light surface corrosion "
    "on the lower torque link, classified as Cat-1 per CMM 32-11-04. The affected area was "
    "cleaned, treated with CIC-2 corrosion inhibitor, and re-protected per the approved "
    "process. The condition does not affect airworthiness and continued operation is "
    "permitted with re-inspection at the next A-check.",

    "An anomaly was noted in the cabin pressurization controller during the post-flight test, "
    "with the outflow valve commanding fully open for approximately 2 seconds during the "
    "automatic schedule transition. Subsequent ground tests were unable to reproduce the "
    "condition, and BITE data showed no fault codes. The event has been logged under "
    "investigation reference INV-21-2026-0418 for continued trend monitoring.",
]

MIR_RECOMMENDATIONS = [
    "Recommend continued operation with monitoring per the engineering surveillance plan.",
    "Recommend component replacement at the next available C-check, not to exceed 1,500 FH.",
    "Recommend re-inspection at the next A-check; no operational restriction required.",
    "Recommend referral to engineering for trend analysis before next heavy maintenance visit.",
    "Recommend dispatch under MEL Cat-B (10 days) pending parts availability.",
]

def gen_mir(i: int) -> str:
    aircraft, tail, engine, op = random.choice(AIRCRAFT_FLEET)
    check = random.choice(CHECK_LEVELS)
    ata, ata_name = random.choice(ATA_CHAPTERS)
    inspector = random.choice(INSPECTORS)
    date_d = random.randint(1, 28)
    date_m = random.randint(1, 6)
    fh = random.randint(8000, 42000)
    fc = random.randint(3000, 18000)
    work_order = f"MIR/2026/{random.randint(10000, 99999)}"

    findings = random.sample(MIR_FINDINGS, k=random.randint(2, 4))
    actions = random.sample(MIR_ACTIONS, k=len(findings))
    findings_block = "\n".join(
        f"  {n+1}. {f}\n     ACTION: {a}"
        for n, (f, a) in enumerate(zip(findings, actions))
    )

    return f"""MAINTENANCE INSPECTION REPORT

Work Order Number:   {work_order}
Date of Inspection:  {date_d:02d}/{date_m:02d}/2026
Station:             Delhi (DEL) — Hangar Bay 3

AIRCRAFT DETAILS

Aircraft Type:       {aircraft}
Registration:        {tail}
Operator:            {op}
Total Flight Hours:  {fh:,}
Total Flight Cycles: {fc:,}
Engine Type:         {engine}

INSPECTION

Check Level:         {check}
ATA Chapter:         {ata} — {ata_name}
Reference Manual:    AMM Rev. {random.randint(38, 47)}, Task {ata}-{random.randint(11, 89)}-{random.randint(10, 99):02d}

FINDINGS AND CORRECTIVE ACTIONS

{findings_block}

INSPECTOR'S NARRATIVE

{random.choice(MIR_NARRATIVES)}

{random.choice(MIR_RECOMMENDATIONS)}

CERTIFICATION

Aircraft is hereby certified airworthy for return to service in accordance with the
approved maintenance program. All applicable Airworthiness Directives reviewed and
found compliant.

Inspected by:        {inspector}
DGCA Licence No.:    AME-{random.randint(10000, 99999)}
Signature:           _____________________   Date: {date_d:02d}/{date_m:02d}/2026

Next Inspection Due: {min(date_d + random.randint(60, 120), 28):02d}/{(date_m + random.randint(2, 4)) % 12 or 12:02d}/2026
"""


# ---------------------------------------------------------------------------
# Flight Test Reports — 10
# ---------------------------------------------------------------------------

TEST_TYPES = [
    ("Stall Speed Verification",      "stall warning system, AoA threshold"),
    ("Climb Performance Evaluation",  "rate of climb, fuel burn, time to altitude"),
    ("Single-Engine Out Handling",    "Vmca, asymmetric thrust, rudder authority"),
    ("Cruise Performance Validation", "TAS at FL370, SFC, range factor"),
    ("Autopilot Coupled Approach",    "ILS CAT-IIIA capture, glideslope hold"),
    ("Crosswind Landing Limit Demo",  "max demonstrated crosswind, rudder/aileron coordination"),
    ("Brake Energy Limit Test",       "RTO at MTOW, brake temperatures, fuse plug release"),
    ("Stall Warning Calibration",     "stick shaker activation AoA, margin to stall"),
    ("VMU Verification",              "minimum unstick speed at aft CG, tail clearance"),
    ("Wet Runway Stopping Distance",  "anti-skid efficiency, stopping distance ratio"),
]

WEATHER_CONDITIONS = [
    "CAVOK, wind 270/08, OAT 26°C", "Few CU at 4000ft, wind 090/12, OAT 18°C",
    "BKN at 8000ft, wind calm, OAT 14°C", "SCT at 12000ft, wind 180/15, OAT 22°C",
    "CAVOK, wind 360/06, OAT 31°C",
]

OBSERVATIONS_POOL = [
    "Pitch attitude steady within ±0.5° of target throughout maneuver.",
    "Engine parameters remained within nominal envelope during entire test sequence.",
    "Stick force gradient consistent with predicted simulator response.",
    "Roll control authority adequate at all tested conditions; no adverse handling noted.",
    "EICAS/ECAM displays remained clean; no nuisance alerts during test.",
    "Buffet onset noted at α = 9.4°, well clear of stall AoA (12.8°).",
    "Cabin pressure schedule tracked normally; max ΔP within limit.",
    "Hydraulic systems Green and Yellow maintained nominal pressure (3000 psi ± 50).",
    "FADEC reported no exceedances; engine vibration < 0.4 IPS throughout.",
    "Landing gear retraction time 9.8s (spec: ≤ 12.0s); extension 11.4s.",
]

# Prose discussion blocks for FTR — qualitative pilot/FTE narrative
FTR_DISCUSSIONS = [
    "Aircraft handling characteristics throughout the test envelope were qualitatively assessed "
    "as satisfactory, with no compensatory pilot inputs required to maintain target attitudes. "
    "Initial pitch response was crisp and well-damped, with predicted overshoot of 1.8° "
    "decaying within a single cycle. Roll asymmetry of approximately 0.4° was noted at "
    "flaps-15 configuration, attributed to fuel imbalance present at the start of the maneuver "
    "sequence, and considered insignificant for certification purposes.",

    "The crew noted a mild lateral PIO tendency during the first approach in the gust simulation "
    "leg, which was attributed to the unfamiliar augmented control law. After the second "
    "exposure the pilot was able to suppress the tendency through reduced stick input "
    "amplitude. Recommend a brief familiarization brief be added to the type-rating syllabus "
    "covering this specific control law mode.",

    "Engine response during the rapid-power-application sequence was within predicted timing, "
    "with spool-up from idle to TOGA achieved in 5.9 seconds (specification ≤ 8.0 s). No "
    "compressor stall or surge indications were observed at any combination of altitude and "
    "speed flown. Recommend release of the engine envelope expansion package for line "
    "operations pending completion of the final cold-weather test campaign.",

    "Overall the aircraft demonstrated handling qualities consistent with Level 1 per "
    "MIL-STD-1797A criteria across the tested envelope. One minor finding: the FBW law "
    "exhibited a brief 0.3 g vertical disturbance at the flaps transition point, which "
    "was traced to a known software characteristic scheduled for resolution in software "
    "build P5.2. No safety-of-flight concern; acceptable for continued certification testing.",

    "All test points within the planned envelope were completed satisfactorily. The aircraft "
    "exhibited stable lateral-directional behavior throughout the asymmetric thrust "
    "investigation, with the rudder providing adequate authority to counter the yawing "
    "moment generated by the simulated engine failure. Stick force per g remained linear "
    "and well within the predicted band. No exceedances were recorded.",
]

FTR_RECOMMENDATIONS = [
    "Recommend approval of the test point for certification basis.",
    "Recommend re-flight at fwd CG / max weight before release.",
    "Recommend continued investigation under engineering surveillance.",
    "Recommend incorporation into FCOM Vol. 2, Chapter 5 — Abnormal Procedures.",
    "Recommend release to line operations with no further restriction.",
]

def gen_ftr(i: int) -> str:
    aircraft, tail, engine, op = random.choice(AIRCRAFT_FLEET)
    test_name, focus = random.choice(TEST_TYPES)
    pilot = random.choice(TEST_PILOTS)
    fto = random.choice(["F/O P. Iyengar", "F/O R. Bhattacharya", "F/O A. Krishnan"])
    fte = random.choice(["FTE V. Subramanian", "FTE M. Rao", "FTE K. Banerjee"])
    date_d = random.randint(1, 28); date_m = random.randint(1, 6)
    test_no = f"FTR-{random.choice(['DA', 'BL', 'HY'])}-2026-{random.randint(100, 999)}"
    fh_test = random.randint(2, 5)
    weather = random.choice(WEATHER_CONDITIONS)
    obs = random.sample(OBSERVATIONS_POOL, k=4)
    obs_block = "\n".join(f"  • {o}" for o in obs)
    payload = random.randint(60, 95)
    fuel = random.randint(8, 24)
    conclusion = random.choice([
        "PASS — all acceptance criteria met. Recommended for certification.",
        "PASS WITH OBSERVATIONS — see noted items; cleared subject to FCOM revision.",
        "PARTIAL PASS — re-fly required for envelope point #3 due to weather.",
        "PASS — exceeds spec margin by 8%. No further action required.",
    ])

    return f"""FLIGHT TEST REPORT

Test Report Number:  {test_no}
Test Date:           {date_d:02d}/{date_m:02d}/2026
Test Duration:       {fh_test}h {random.randint(10, 55)}min
Test Location:       Bengaluru (BLR) — Flight Test Range B

TEST AIRCRAFT

Aircraft Type:       {aircraft}
Registration:        {tail}
Engine Configuration: 2 × {engine}
Test Configuration:  {payload}% MTOW, fwd CG @ {random.randint(18, 28)}% MAC

TEST CREW

Test Pilot:          {pilot}
First Officer:       {fto}
Flight Test Engineer: {fte}

TEST OBJECTIVE

{test_name} — Verify {focus} for the subject aircraft at the conditions defined in
Test Plan {test_no}, in accordance with CAR-23 / CS-25 § 25.{random.randint(101, 875)}.

TEST CONDITIONS

Weather:             {weather}
Test Altitude(s):    FL{random.randint(80, 410):03d} — FL{random.randint(80, 410):03d}
Fuel On Board (Start): {fuel}.{random.randint(0, 9)} tonnes
Aircraft Mass:       {random.randint(45, 280)} tonnes
CG Position:         {random.randint(18, 38)}.{random.randint(0, 9)}% MAC

OBSERVATIONS

{obs_block}

DISCUSSION

{random.choice(FTR_DISCUSSIONS)}

{random.choice(FTR_RECOMMENDATIONS)}

CONCLUSION

{conclusion}

Approved by:         {pilot}
FTE Concurrence:     {fte}
"""


# ---------------------------------------------------------------------------
# Service Bulletins — 10
# ---------------------------------------------------------------------------

# Prose background blocks for SB — manufacturer's narrative explaining context
SB_BACKGROUNDS = [
    "The original design assumption regarding the operating temperature range of this component "
    "has been challenged by field experience accumulated over the past 18 months. Investigation "
    "of returned units has identified that prolonged exposure to high-cycle vibration in "
    "combination with cold-soak conditions can lead to accelerated wear of the internal "
    "bearing surfaces. To date there have been 14 confirmed in-service occurrences across "
    "the global fleet, none of which have resulted in any safety-of-flight consequence. "
    "Engineering risk assessment categorizes the residual risk as Low after compliance with "
    "this Service Bulletin.",

    "A recent in-service occurrence on an operator in the Asia-Pacific region prompted a "
    "fleet-wide review of the component history. The investigation determined that aircraft "
    "operating in high-humidity, high-cycle environments are statistically more likely to "
    "exhibit the wear pattern described in section 3. While no immediate corrective action "
    "is mandated, the manufacturer strongly recommends compliance within the timeframe "
    "specified to maintain expected component reliability and dispatch availability.",

    "This Service Bulletin is issued in response to a small number of operator-reported "
    "events involving intermittent system status messages on the affected ATA chapter. Root "
    "cause analysis attributed the events to a latent software state that can occur when the "
    "system is energized within a specific 4-second window following the loss-of-bus event. "
    "The probability of encountering this state is assessed as remote, but the manufacturer "
    "has elected to release a software update to eliminate the failure mode.",

    "Following the certification flight test campaign for the most recent engine variant, "
    "an additional thermal margin requirement was identified in the bleed air duct manifold "
    "downstream of the precooler. This Service Bulletin describes the inspection procedure "
    "and provides part number information for the strengthened replacement assembly. "
    "Operators with affected MSN are advised to schedule compliance at the next available "
    "C-check to minimize operational disruption.",

    "Continued surveillance of the in-service fleet has revealed that approximately 4% of "
    "the affected population exhibits a measurable performance shift in the subject system "
    "after 6,000 flight hours. The shift is gradual and does not produce any flight deck "
    "indication, but can lead to a small reduction in system efficiency. Compliance with "
    "this Service Bulletin will restore performance to within the original specification "
    "and is recommended at the next scheduled maintenance opportunity.",
]

SB_RISK_ASSESSMENTS = [
    "Residual risk after compliance: LOW.",
    "Residual risk after compliance: NEGLIGIBLE.",
    "Risk classification per FHA: MINOR.",
    "Risk classification per FHA: MAJOR — operator action required.",
    "Risk classification per FHA: HAZARDOUS — compliance is mandatory.",
]

SB_SUBJECTS = [
    ("Engine Fuel Pump Inspection",
     "potential premature wear of impeller bearing under specific operating conditions",
     "Inspect impeller bearing per Figure 2 using borescope. If wear exceeds 0.15 mm, replace per AMM 73-12-04.",
     "Recommended"),
    ("Hydraulic Reservoir Fill Valve Replacement",
     "corrosion of fill valve seat observed in field operations exceeding 8,000 FH",
     "Replace fill valve assembly P/N HRV-2241-01 with improved variant P/N HRV-2241-02.",
     "Mandatory"),
    ("Wing Leading Edge Slat Track Lubrication Procedure Update",
     "intermittent slat actuator stall reports traced to insufficient lubrication",
     "Apply MIL-PRF-81322 grease per revised procedure detailed in Appendix A every 1500 FH.",
     "Recommended"),
    ("Cargo Door Latch Actuator Software Update",
     "rare nuisance unlock indication on EICAS during taxi",
     "Upgrade actuator firmware from v3.4.1 to v3.5.0 using DCDS loader per maintenance task 52-71-01.",
     "Recommended"),
    ("Main Landing Gear Pintle Pin Inspection",
     "small population of pintle pins found with surface micro-cracks during teardown",
     "Perform fluorescent dye penetrant inspection per NDT-32-08-PT-04 on next A-Check.",
     "Mandatory"),
    ("APU Air Inlet Door Hinge Replacement",
     "hinge bushing wear leading to door rattle on ground operations",
     "Replace bushing P/N APU-INLT-BSH-04 with improved CRES bushing P/N APU-INLT-BSH-05.",
     "Recommended"),
    ("Cabin Pressure Outflow Valve Position Sensor Update",
     "drift of position sensor output observed > 5,000 FH causing slow OFV response",
     "Replace position sensor P/N OFV-PS-2301 and reprogram CPC per task 21-31-12.",
     "Mandatory"),
    ("Engine Nacelle Anti-Ice Duct Inspection",
     "thermal cycling fatigue cracking observed on bleed air duct elbow",
     "Inspect duct elbow per Figure 3; replace if any crack length > 6 mm is detected.",
     "Mandatory"),
    ("Fuel Quantity Indicating System Recalibration",
     "drift in fuel quantity reading observed across multiple operators",
     "Perform calibration per FCOM 28-41-00, comparing to drip-stick measurement at three fuel levels.",
     "Recommended"),
    ("Brake Control Unit Software Update",
     "FAA reported potential anti-skid logic discrepancy under wet runway conditions",
     "Update BCU software from v2.18 to v2.20 per maintenance procedure 32-44-10.",
     "Mandatory"),
]

def gen_sb(i: int) -> str:
    aircraft, _, engine, _ = random.choice(AIRCRAFT_FLEET)
    title, reason, action, classification = SB_SUBJECTS[i % len(SB_SUBJECTS)]
    ata, ata_name = random.choice(ATA_CHAPTERS)
    issue_d = random.randint(1, 28); issue_m = random.randint(1, 6)
    sb_no = f"SB-{aircraft.split()[0][:3].upper()}-{ata}-{random.randint(100, 999)}"
    rev = random.choice(["Original Issue", "Revision 01", "Revision 02"])
    cost = random.randint(180, 4200)
    labor = random.randint(2, 18)
    msn_from = random.randint(1001, 5000); msn_to = msn_from + random.randint(50, 800)
    engineer = random.choice(ENGINEERS)

    return f"""SERVICE BULLETIN

Service Bulletin No: {sb_no}
Issue Date:          {issue_d:02d}/{issue_m:02d}/2026
Revision Status:     {rev}
ATA Chapter:         {ata} — {ata_name}
Classification:      {classification}

SUBJECT

{title}

APPLICABILITY

Aircraft Type:       {aircraft}
Serial Numbers:      MSN {msn_from} through MSN {msn_to}
Engine(s):           {engine}
Effectivity:         All aircraft within the serial range listed above unless previously
                     modified per SB-{aircraft.split()[0][:3].upper()}-{ata}-{random.randint(100, 999)} Rev. 02.

REASON FOR ISSUE

This Service Bulletin is issued to address {reason}. Operator reports and in-service
investigations indicate that continued operation without the corrective action described
herein may result in degraded system performance and increased maintenance burden.

BACKGROUND AND RISK ASSESSMENT

{random.choice(SB_BACKGROUNDS)}

{random.choice(SB_RISK_ASSESSMENTS)}

DESCRIPTION OF CHANGE

{action}

COMPLIANCE

Recommended compliance: Within {random.choice(['1,500', '3,000', '4,500', '6,000'])} flight hours
or {random.choice(['6', '12', '18', '24'])} months from the date of this Service Bulletin,
whichever occurs first.

ESTIMATED LABOR

Manhours:            {labor} MH per aircraft (two technicians, station-level)
Estimated Material Cost: USD {cost:,}
Special Tooling:     None / Standard line tooling

REFERENCES

— Aircraft Maintenance Manual (AMM) Chapter {ata}
— Illustrated Parts Catalog (IPC) Chapter {ata}
— Component Maintenance Manual {ata}-{random.randint(10, 89)}-{random.randint(10, 99):02d}

APPROVED BY

{engineer}
Engineering Authority: EA-{random.randint(1000, 9999)}
Type Certification:    TC-{random.choice(['DGCA-India', 'EASA', 'FAA'])}-{random.randint(2014, 2025)}
"""


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> None:
    manifest = []
    for i in range(10):
        text = gen_mir(i)
        fname = f"maintenance_inspection_{i:02d}.txt"
        (DOCS / fname).write_text(text)
        manifest.append({"filename": fname, "doc_type": "maintenance_inspection"})
    for i in range(10):
        text = gen_ftr(i)
        fname = f"flight_test_{i:02d}.txt"
        (DOCS / fname).write_text(text)
        manifest.append({"filename": fname, "doc_type": "flight_test"})
    for i in range(10):
        text = gen_sb(i)
        fname = f"service_bulletin_{i:02d}.txt"
        (DOCS / fname).write_text(text)
        manifest.append({"filename": fname, "doc_type": "service_bulletin"})

    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (HERE / "README.md").write_text(
        "# Aircraft engineering sample set\n\n"
        f"{len(manifest)} synthetic aerospace documents across 3 types:\n\n"
        "- **Maintenance Inspection Report (MIR)** — A/B/C/D-check findings, "
        "ATA-chapter referenced, fleet-realistic.\n"
        "- **Flight Test Report (FTR)** — performance / handling / certification "
        "test runs per CAR-23 / CS-25.\n"
        "- **Service Bulletin (SB)** — manufacturer-issued advisories, ATA-chapter "
        "referenced, with compliance + cost + tooling.\n\n"
        "Generated synthetically by `generate.py` with a fixed seed for reproducibility. "
        "Used as a discover benchmark fixture, not training data.\n"
    )

    print(f"wrote {len(manifest)} aircraft documents across 3 types")


if __name__ == "__main__":
    main()
