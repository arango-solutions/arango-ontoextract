# Energy Utility Grid Operations and Asset Management

> Synthetic demonstration document for AOE ontology extraction. All utilities,
> substations, feeders, meters, incidents, crews, customers, and identifiers are
> fictional.

## Overview

Evergreen Power and Light is a fictional electric utility serving residential,
commercial, industrial, municipal, and wholesale customers across a mixed urban
and rural service territory. The utility operates generation resources,
transmission lines, distribution feeders, substations, transformers, protective
devices, advanced meters, distributed energy resources, control centers, field
crews, vegetation programs, and outage response processes.

This document is intended for large-document demonstrations. It contains
interconnected concepts suitable for ontology extraction: assets belong to
networks, sensors monitor assets, events affect assets, work orders dispatch
crews, customers are connected to service points, meters measure usage,
distributed resources export power, and regulatory programs measure reliability.

## Utility Operating Model

Evergreen Power and Light has the following major divisions:

- Grid Operations, which manages real-time transmission and distribution
  control.
- Asset Management, which maintains equipment registries, inspection programs,
  maintenance strategies, and replacement plans.
- Distribution Engineering, which plans feeder capacity, voltage regulation,
  protection coordination, and new service connections.
- Transmission Planning, which studies bulk power flows, interconnection
  requests, and reliability criteria.
- Customer Operations, which manages service orders, billing, payments,
  customer programs, and outage communications.
- Field Services, which dispatches line crews, meter technicians, vegetation
  crews, substation technicians, and trouble responders.
- Regulatory Compliance, which manages reliability reporting, safety standards,
  environmental permits, and market obligations.

## Network Model

### Service Territory

A Service Territory is the geographic area where the utility provides electric
service. Evergreen divides the service territory into regions, districts,
operating centers, substations, feeders, circuits, service zones, and outage
prediction areas.

Each region has a regional manager, control center desk, field depot,
vegetation cycle, storm plan, and reliability targets.

### Substation

A Substation transforms voltage, switches circuits, protects equipment, and
connects transmission or distribution networks. Substation attributes include
substation identifier, name, voltage class, geographic coordinates, operating
region, bus configuration, transformer bank, breaker list, protection scheme,
communications status, SCADA status, security classification, and criticality.

The Cedar Hill Substation contains two 115 kV incoming lines, two 115/13.2 kV
power transformers, four distribution feeder breakers, capacitor banks,
voltage regulators, battery system, control house, RTU, protective relays, and
security cameras.

### Feeder

A Feeder is a distribution circuit originating at a substation breaker. It
serves customers through primary lines, laterals, transformers, service drops,
and meters.

Feeder attributes include feeder identifier, nominal voltage, substation,
breaker, load profile, peak demand, customer count, critical customers,
overhead mileage, underground mileage, protective device count, distributed
generation capacity, and reliability history.

Feeder CH-1204 serves 8,420 customers, including a hospital, two schools, one
water treatment plant, and a refrigerated food warehouse.

### Asset

An Asset is any physical or logical component used to deliver electric service.
Asset classes include transmission line, distribution line, pole, crossarm,
insulator, conductor, underground cable, transformer, breaker, recloser, fuse,
switch, capacitor bank, regulator, relay, meter, sensor, battery, inverter,
communication gateway, and control system.

Assets have asset identifiers, installation dates, manufacturers, model
numbers, ratings, locations, parent assets, maintenance history, inspection
history, condition scores, failure modes, and replacement cost.

## Customer and Metering Entities

### Customer

A Customer is an individual or organization receiving electric service.
Customers have customer account number, customer class, name, billing address,
service address, rate tariff, payment status, contact preferences, life-support
flag, medical baseline flag, outage notification preference, and program
enrollment.

Customer classes include residential, small commercial, large commercial,
industrial, municipal, agricultural, street lighting, and wholesale.

### Service Point

A Service Point is a physical delivery location. It links customer account,
premise, meter, transformer, feeder, rate tariff, service voltage, phase,
connection status, and load profile.

One premise may have multiple service points, such as a commercial building
with separate house meter, tenant meters, solar meter, and electric vehicle
charging meter.

### Meter

A Meter records electric usage, demand, voltage, outage events, tamper events,
and interval reads. Meter types include advanced meter, net meter, demand
meter, transformer-rated meter, production meter, and temporary construction
meter.

Advanced meters communicate through radio mesh networks, cellular backhaul, or
power-line carrier. Each meter has meter number, firmware version, register
configuration, multiplier, communication status, last read date, and outage
last gasp capability.

### Usage Read

Usage Reads include interval energy, demand, reactive power, voltage, current,
power factor, event flags, and estimated-read indicators. Interval data is used
for billing, load forecasting, outage detection, theft analytics, and demand
response measurement.

## Operational Systems

### SCADA

SCADA monitors and controls substations, breakers, switches, capacitor banks,
regulators, generation resources, and telemetry points. SCADA points include
analog measurements, status indications, alarms, controls, setpoints, and
communication quality.

### Advanced Distribution Management System

The Advanced Distribution Management System manages network topology,
switching plans, fault location, isolation, service restoration, voltage
optimization, distributed energy resource awareness, and outage analysis.

ADMS receives telemetry from SCADA, meter events, outage calls, crew updates,
weather feeds, asset registry data, and geographic information systems.

### Outage Management System

The Outage Management System groups customer calls, meter last-gasp events,
SCADA alarms, and crew observations into outage incidents. It estimates outage
location, affected customers, cause, restoration time, crew assignment, and
customer notifications.

### Geographic Information System

GIS maintains network connectivity, asset locations, conductor spans, pole
attachments, service transformers, underground cable routes, landbase layers,
right-of-way boundaries, and vegetation management zones.

## Reliability Events

### Outage Event

An Outage Event is a loss of electric service. It includes outage identifier,
start time, end time, affected customers, affected service points, device that
operated, suspected cause, confirmed cause, crew, estimated restoration time,
actual restoration time, and regulatory exclusion flag.

Outage causes include tree contact, animal contact, lightning, wind, ice,
equipment failure, vehicle accident, dig-in, planned maintenance, transmission
constraint, wildfire mitigation shutoff, and unknown cause.

### Momentary Interruption

A Momentary Interruption is a brief outage typically caused by recloser
operation. It has duration, device, feeder, affected customers, operation
sequence, fault current, and restoration status.

### Power Quality Event

Power Quality Events include voltage sag, voltage swell, flicker, harmonic
distortion, frequency deviation, neutral issue, phase imbalance, and transient
overvoltage. Events can be reported by meters, customer complaints, sensors,
or field measurements.

## Work Management

### Work Order

A Work Order authorizes field or shop work. It has work order number, work
type, priority, asset, location, planner, scheduler, assigned crew, required
skills, required materials, safety hazards, switching requirements, outage
requirements, planned start, planned finish, actual start, actual finish, and
completion notes.

Work order types include corrective maintenance, preventive maintenance,
inspection, emergency repair, capital construction, service connection,
disconnect, reconnect, meter exchange, vegetation trimming, and storm damage
repair.

### Crew

A Crew is a group of workers assigned to field tasks. Crew types include line
crew, trouble crew, underground crew, substation crew, meter crew, vegetation
crew, relay technician crew, and contract crew.

Crew attributes include crew identifier, supervisor, members, skills,
equipment, home base, shift, availability, fatigue status, safety briefing
status, and current assignment.

### Switching Order

A Switching Order defines the sequence of operations required to isolate,
energize, de-energize, ground, or transfer electric equipment. It contains
switch steps, device identifiers, operator, field verifier, hold points,
clearance boundaries, tagging requirements, and approval status.

Switching orders require coordination between control center operators and
field crews. Incorrect switching can create safety hazards or expand outages.

## Asset Management

### Inspection

Inspection evaluates asset condition. Inspection types include pole inspection,
infrared inspection, substation inspection, transformer oil test, breaker
timing test, relay calibration, vegetation patrol, drone inspection, and
underground cable partial discharge test.

Inspection findings include defect type, severity, location, photo evidence,
recommended action, due date, inspector, and condition score.

### Maintenance Strategy

Maintenance strategies include run-to-failure, time-based maintenance,
condition-based maintenance, risk-based replacement, predictive maintenance,
and reliability-centered maintenance.

High-criticality assets such as substation transformers receive condition-based
maintenance using dissolved gas analysis, oil quality, load history, bushing
monitoring, thermal imaging, and vibration monitoring.

### Failure Mode

Failure modes include insulation breakdown, conductor fatigue, corrosion,
overheating, relay misoperation, breaker mechanism failure, transformer winding
failure, bushing failure, cable water treeing, vegetation contact, wildlife
contact, and communication failure.

Failure mode analysis links asset class, operating environment, age, loading,
maintenance history, inspection findings, and consequence of failure.

## Distributed Energy Resources

### DER Asset

Distributed Energy Resources include rooftop solar, community solar, battery
storage, electric vehicle chargers, standby generators, combined heat and
power, demand response resources, and smart thermostats.

Each DER asset has interconnection application, capacity, inverter model,
protection settings, export limit, tariff, owner, operator, commissioning date,
and telemetry availability.

### Interconnection Application

Interconnection Application requests permission to connect DER to the grid.
It includes applicant, service point, equipment, capacity, single-line diagram,
protection study, hosting capacity screen, required upgrades, agreement, and
permission to operate.

### Demand Response Event

Demand Response Event requests load reduction or load shifting. It has event
identifier, program, enrolled customers, start time, end time, baseline, actual
load, performance, incentive payment, and nonperformance reason.

## Major Incident Scenario

### Storm Event: Derecho Windstorm

A derecho windstorm crossed the service territory on July 18. Sustained winds
exceeded 60 miles per hour, and gusts exceeded 85 miles per hour in the North
Valley region. The event caused tree contact, broken poles, downed conductors,
substation communication failures, and blocked road access.

The storm incident affected 148,000 customers at peak. The Outage Management
System created 2,480 outage incidents, 740 wire-down tickets, 93 critical
customer tickets, and 38 public safety priority tickets.

### Incident Command

Evergreen activated the emergency operations center. Incident Command roles
included incident commander, operations section chief, planning section chief,
logistics section chief, safety officer, public information officer, liaison
officer, damage assessment lead, mutual assistance coordinator, and customer
communications lead.

### Restoration Priorities

Restoration priorities followed the storm plan:

- Make downed wires safe.
- Restore transmission supply to substations.
- Restore hospitals, emergency operations centers, water facilities, and
  public safety customers.
- Repair main feeders.
- Repair laterals.
- Restore individual service drops.
- Complete clean-up and permanent repairs.

### Damage Assessment

Damage assessors inspected feeders and recorded broken poles, damaged
crossarms, conductor spans down, transformer failures, blown fuses, recloser
lockouts, vegetation conflicts, inaccessible roads, and required materials.

Damage assessment records included GPS coordinates, photos, asset identifiers,
severity, repair estimate, required crew type, and safety hazards.

### Mutual Assistance

Evergreen requested mutual assistance from three neighboring utilities and two
contractor organizations. Incoming crews were assigned staging areas, safety
briefings, feeder maps, radio channels, lodging, fuel access, material kits,
and crew guides.

### Customer Communications

Customer communications used outage maps, text alerts, email alerts, IVR
messages, social media updates, municipal briefings, medically vulnerable
customer outreach, and press releases. Estimated restoration times were updated
as crews completed patrols and switching plans.

## Regulatory Metrics

Reliability metrics include System Average Interruption Duration Index,
System Average Interruption Frequency Index, Customer Average Interruption
Duration Index, Customer Average Interruption Frequency Index, Momentary
Average Interruption Frequency Index, customers interrupted, customer minutes
interrupted, and major event day exclusions.

Safety metrics include OSHA recordable incidents, vehicle incidents, near
misses, public contact incidents, wire-down response time, switching errors,
and contractor safety observations.

## Grid Modernization Programs

Evergreen has active modernization programs:

- Advanced metering deployment.
- Feeder automation.
- Fault location isolation and service restoration.
- Volt-var optimization.
- Substation modernization.
- Underground cable replacement.
- Wildfire risk mitigation.
- Vegetation analytics.
- Distributed energy resource management.
- Grid-edge sensor deployment.
- Customer outage notification modernization.

Each program has business case, budget, schedule, benefits, affected assets,
stakeholders, milestones, risks, dependencies, and performance metrics.

## Ontology Extraction Hints

Useful classes include Utility, Division, Service Territory, Region,
Substation, Feeder, Asset, Transformer, Breaker, Recloser, Meter, Customer,
Service Point, Usage Read, SCADA Point, ADMS, OMS, GIS, Outage Event,
Momentary Interruption, Power Quality Event, Work Order, Crew, Switching
Order, Inspection, Maintenance Strategy, Failure Mode, DER Asset,
Interconnection Application, Demand Response Event, Storm Incident, Incident
Command Role, Damage Assessment, Mutual Assistance Request, Regulatory Metric,
and Modernization Program.

Useful relationships include substation feeds feeder, feeder serves service
point, customer has service point, service point has meter, meter records usage
read, asset belongs to feeder, inspection evaluates asset, work order repairs
asset, crew executes work order, switching order isolates asset, outage event
affects customer, storm incident causes outage event, DER asset connects to
service point, and regulatory metric measures reliability.
