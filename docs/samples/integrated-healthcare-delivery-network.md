# Integrated Healthcare Delivery Network Operations

> Synthetic demonstration document for AOE ontology extraction. All patients,
> providers, facilities, claims, identifiers, events, and organizations are
> fictional and intended for demonstration only.

## Overview

Riverside Integrated Care Network is a fictional regional health system that
operates hospitals, ambulatory clinics, laboratories, pharmacies, imaging
centers, telehealth services, home health programs, accountable care
contracts, and clinical research sites. This document describes the network's
clinical, administrative, quality, and population-health operations.

The document is intentionally large and structured to demonstrate ontology
extraction across healthcare entities: patients receive care, encounters occur
at facilities, providers document diagnoses, orders request procedures,
laboratories produce results, medications are administered, claims are
submitted to payers, care gaps are identified, and quality programs measure
outcomes.

## Organization Structure

Riverside Integrated Care Network contains the following operating units:

- Riverside Medical Center, a 620-bed tertiary hospital.
- North Valley Community Hospital, a 180-bed acute care hospital.
- Riverside Children's Pavilion, a pediatric specialty hospital.
- Riverside Ambulatory Group, a network of 42 outpatient clinics.
- Riverside Diagnostic Services, including laboratories and imaging centers.
- Riverside Home Health, providing skilled nursing and therapy visits.
- Riverside Specialty Pharmacy, managing high-cost specialty medications.
- Riverside Health Plan, a provider-sponsored insurance plan.
- Riverside Clinical Research Institute, coordinating sponsored trials.

Each operating unit has a facility identifier, National Provider Identifier,
tax identification number, accreditation status, service lines, departments,
care teams, and quality reporting obligations.

## Patient Identity and Registration

### Patient

A Patient is an individual receiving healthcare services. Each patient has a
medical record number, enterprise master patient identifier, full legal name,
preferred name, date of birth, sex assigned at birth, gender identity,
pronouns, language preference, race, ethnicity, address, contact numbers,
email, emergency contact, guarantor, and consent preferences.

Patient records may be linked through a Master Patient Index. Potential
duplicates are reviewed by health information management staff. Merge decisions
record source records, surviving record, demographic evidence, and audit trail.

### Coverage

Coverage describes payer responsibility for healthcare services. A patient may
have primary coverage, secondary coverage, self-pay status, charity care
eligibility, or workers compensation coverage.

Coverage attributes include payer name, plan name, member identifier, group
number, effective date, termination date, subscriber relationship, copay,
coinsurance, deductible, prior authorization rules, and referral requirements.

### Consent

Consent records include general treatment consent, telehealth consent, research
authorization, release of information, behavioral-health data restrictions,
substance-use confidentiality restrictions, and organ donation preferences.

## Care Delivery Entities

### Encounter

An Encounter is an interaction between a patient and the health system.
Encounter types include inpatient admission, emergency department visit,
outpatient appointment, urgent care visit, telehealth visit, home health visit,
observation stay, ambulatory surgery, infusion visit, and laboratory-only
encounter.

Each encounter has an encounter identifier, patient, facility, department,
attending provider, care team, start time, end time, status, location history,
reason for visit, chief complaint, acuity, diagnosis list, procedure list,
orders, notes, discharge disposition, and billing account.

### Care Team

A Care Team coordinates services for a patient. Roles include attending
physician, resident, nurse practitioner, physician assistant, registered nurse,
case manager, pharmacist, social worker, dietitian, physical therapist,
occupational therapist, respiratory therapist, care coordinator, and community
health worker.

Care team assignments may be encounter-specific or longitudinal. A primary
care provider assignment can span multiple encounters and population-health
programs.

### Clinical Note

A Clinical Note documents observations, assessments, plans, procedures,
handoffs, discharge instructions, and patient education. Note types include
history and physical, progress note, consult note, operative report, discharge
summary, nursing note, medication reconciliation note, radiology report, and
pathology report.

Each note has author, cosigner, timestamp, note status, template type, sections,
attestations, amendments, and confidentiality flags.

## Clinical Conditions and Diagnoses

### Problem

A Problem is a longitudinal clinical condition maintained on a problem list.
Examples include type 2 diabetes mellitus, chronic kidney disease, congestive
heart failure, chronic obstructive pulmonary disease, hypertension, depression,
opioid use disorder, pregnancy, asthma, and atrial fibrillation.

Problem attributes include onset date, clinical status, verification status,
severity, laterality, stage, responsible provider, and source encounter.

### Diagnosis

A Diagnosis is assigned during an encounter or claim. It has an ICD-10-CM code,
description, diagnosis type, present-on-admission indicator, ranking, onset
date, and resolution date.

Principal diagnoses drive inpatient reimbursement. Secondary diagnoses capture
comorbidities and complications. Working diagnoses support clinical decision
making before final diagnosis confirmation.

### Risk Factor

Risk factors include tobacco use, alcohol use, housing insecurity, food
insecurity, transportation barriers, occupational exposure, family history,
genetic markers, medication nonadherence, and prior hospitalization.

Risk factors may be captured through social needs screening, clinical notes,
claims history, wearable device data, or patient-reported outcomes.

## Orders and Results

### Order

An Order is a request for a clinical service, medication, laboratory test,
imaging procedure, referral, consult, durable medical equipment, diet, activity,
or nursing intervention.

Orders have ordering provider, priority, indication, order set, start date,
stop date, frequency, status, specimen requirement, scheduling requirement, and
authorization requirement.

### Laboratory Test

Laboratory tests include complete blood count, comprehensive metabolic panel,
hemoglobin A1c, lipid panel, troponin, blood culture, urine culture, viral PCR,
pathology biopsy, genetic panel, and therapeutic drug monitoring.

Laboratory results have result value, unit, reference range, abnormal flag,
critical flag, specimen source, collection time, received time, verified time,
performing laboratory, and interpreting pathologist when applicable.

### Imaging Study

Imaging studies include chest x-ray, CT head, CT angiography, MRI brain,
ultrasound abdomen, mammogram, echocardiogram, nuclear stress test, and PET
scan.

An imaging study has modality, body site, contrast use, protocol, accession
number, technologist, radiologist, preliminary report, final report, impression,
critical result notification, and follow-up recommendation.

## Medication Management

### Medication Order

A Medication Order prescribes a drug, dose, route, frequency, duration, and
indication. Orders may be inpatient medication orders, outpatient prescriptions,
discharge medications, infusion orders, vaccines, or medication samples.

Medication order attributes include generic name, brand name, RxNorm code,
National Drug Code, strength, dosage form, route, schedule, start date, stop
date, refills, dispense quantity, prior authorization status, and formulary
tier.

### Medication Administration

Medication Administration records the actual delivery of medication. It
captures administration time, administered dose, administering nurse, route,
site, barcode scan status, patient refusal, waste documentation, and adverse
reaction.

High-alert medications require independent double-check. Controlled substances
require chain-of-custody documentation and reconciliation between dispensing
cabinets and administration records.

### Medication Reconciliation

Medication reconciliation compares home medications, inpatient medications,
transfer medications, and discharge medications. Discrepancies are categorized
as omission, duplicate therapy, dose mismatch, route mismatch, interaction,
contraindication, or outdated medication.

## Care Pathways

### Diabetes Care Pathway

The diabetes care pathway monitors patients with type 2 diabetes. Measures
include hemoglobin A1c testing, blood pressure control, statin therapy, kidney
function screening, retinal exam, foot exam, medication adherence, nutrition
consultation, and diabetes education.

Care gaps are generated when recommended services are overdue. A care gap has
patient, measure, due date, responsible care manager, outreach status,
resolution status, and evidence source.

### Heart Failure Pathway

The heart failure pathway tracks ejection fraction, NYHA class, guideline
directed medical therapy, daily weights, diuretic adjustment, sodium
restriction, cardiology follow-up, readmission risk, and remote monitoring.

Patients discharged after heart failure admission receive follow-up within
seven days, medication reconciliation within 48 hours, and home scale
instructions.

### Sepsis Pathway

The sepsis pathway begins with screening criteria: suspected infection,
temperature abnormality, heart rate, respiratory rate, white blood cell count,
lactate level, blood pressure, and altered mental status.

Sepsis bundle elements include blood cultures before antibiotics, broad-spectrum
antibiotics, lactate measurement, fluid resuscitation, vasopressor initiation,
repeat lactate, source control, and ICU consult when indicated.

## Population Health Programs

### Risk Stratification

Risk stratification assigns patients to low, rising, high, or complex risk
tiers. Inputs include chronic conditions, prior utilization, medication burden,
social needs, predictive model score, claims cost, recent emergency department
use, and care manager assessment.

### Care Management

Care Management provides longitudinal support. A care manager creates a care
plan with goals, barriers, interventions, tasks, referrals, education topics,
community resources, and follow-up schedule.

Care plan goals may include reducing A1c, improving medication adherence,
securing transportation, completing specialist follow-up, arranging home
equipment, or preventing avoidable readmission.

### Quality Measures

Quality measures include HEDIS measures, CMS Stars measures, hospital
readmission measures, sepsis bundle compliance, surgical site infection rate,
central-line bloodstream infection rate, patient experience scores, preventive
screening rates, and medication adherence measures.

Each measure has denominator criteria, numerator criteria, exclusion criteria,
measurement period, reporting program, steward, score, benchmark, and gap list.

## Claims and Revenue Cycle

### Claim

A Claim requests payment for healthcare services. Claims include institutional
claims, professional claims, dental claims, pharmacy claims, encounter records,
and capitation encounter submissions.

Claim attributes include billing provider, rendering provider, payer, patient,
subscriber, service dates, place of service, diagnosis codes, procedure codes,
revenue codes, modifiers, billed amount, allowed amount, paid amount, denial
reason, and remittance advice.

### Prior Authorization

Prior authorization is required for selected medications, imaging studies,
surgeries, durable medical equipment, and out-of-network referrals. It includes
requesting provider, payer, requested service, clinical documentation, status,
approval number, effective dates, denial reason, appeal status, and peer-to-peer
review.

### Denial Management

Denial management categorizes denials into eligibility, authorization, medical
necessity, coding, timely filing, coordination of benefits, duplicate claim,
and documentation deficiency. Appeals include appeal level, submission date,
supporting documents, outcome, recovered amount, and turnaround time.

## Clinical Research

### Study

A Study is a clinical research protocol with sponsor, principal investigator,
phase, indication, intervention, control arm, inclusion criteria, exclusion
criteria, consent form, IRB approval, enrollment target, study visits, adverse
event reporting, and data capture requirements.

### Participant

A Participant is a patient enrolled in a study. Enrollment includes screening,
consent, randomization, study arm assignment, baseline visit, follow-up visits,
protocol deviations, adverse events, serious adverse events, and withdrawal.

### Research Data

Research data includes lab results, imaging measurements, patient-reported
outcomes, device readings, medication exposure, adverse events, source
documents, case report forms, and monitoring queries.

## Incident Scenario

### Scenario: Complex Diabetic Patient with Readmission Risk

Patient Maria Lopez is a 67-year-old individual with type 2 diabetes,
hypertension, chronic kidney disease stage 3, heart failure with preserved
ejection fraction, and food insecurity. She presents to the emergency department
with shortness of breath, lower extremity edema, and elevated blood glucose.

The emergency department encounter includes triage assessment, vital signs,
laboratory orders, chest x-ray, EKG, IV diuretic administration, cardiology
consult, medication reconciliation, and admission to the telemetry unit.

During admission, the care team identifies barriers: medication cost,
transportation difficulty, limited access to fresh food, and missed nephrology
follow-up. A social worker arranges transportation vouchers and a dietitian
provides low-sodium meal planning.

At discharge, Maria receives a care plan, follow-up appointment, home health
referral, scale, medication list, and instructions to call the heart failure
clinic for weight gain. The population health system creates care gaps for A1c
testing, retinal exam, kidney function screening, and medication adherence.

## Governance and Compliance

Riverside maintains privacy, security, compliance, and clinical governance
programs. HIPAA policies govern protected health information. Audit logs track
record access, break-the-glass access, export events, and amendment requests.

Clinical governance committees review quality events, patient safety incidents,
sentinel events, near misses, medication errors, readmissions, infections,
falls, pressure injuries, and mortality reviews.

## Ontology Extraction Hints

Useful classes include Patient, Encounter, Facility, Provider, Care Team,
Diagnosis, Problem, Risk Factor, Order, Laboratory Test, Laboratory Result,
Imaging Study, Medication Order, Medication Administration, Care Plan, Care
Gap, Quality Measure, Claim, Prior Authorization, Denial, Study, Participant,
Incident, Consent, Coverage, and Audit Event.

Useful relationships include patient has encounter, encounter occurs at
facility, provider authors note, order requests test, test produces result,
medication order leads to administration, problem has diagnosis, patient has
coverage, claim bills encounter, quality measure identifies care gap, care
manager owns care plan, study enrolls participant, and audit event accesses
patient record.
