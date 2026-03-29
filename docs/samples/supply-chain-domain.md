# Supply Chain Management Domain

## Overview

A supply chain encompasses the entire lifecycle of a product from raw material sourcing through manufacturing, distribution, and delivery to the end customer. This document defines the core entities, relationships, and processes in a modern supply chain management system.

## Organizations

A **Supply Chain Partner** is any organization participating in the supply chain. Partners are categorized as:

- **Supplier** — provides raw materials or components. Characterized by supplier rating, lead time, minimum order quantity, and geographic location. Suppliers undergo periodic quality audits.
- **Manufacturer** — transforms raw materials into finished goods. Has production capacity, manufacturing processes, and quality certifications (ISO 9001, ISO 14001).
- **Distributor** — an intermediary that manages inventory and fulfills orders to retailers. Operates one or more warehouses.
- **Retailer** — sells products to end consumers through physical stores or e-commerce channels.
- **Logistics Provider** — handles transportation and shipping between supply chain nodes. Offers different shipping methods (ground, air, ocean, rail).

## Products and Materials

A **Product** has a SKU, name, description, unit price, weight, dimensions, and category. Products exist in a hierarchy:

- **Raw Material** — a basic input to manufacturing (e.g., steel, cotton, silicon). Has a grade and source region.
- **Component** — an intermediate part assembled from raw materials (e.g., circuit board, engine block). Has a bill of materials.
- **Finished Good** — a product ready for sale to customers. Has a retail price and warranty period.

A **Bill of Materials (BOM)** defines the hierarchical composition of a product — which components and raw materials are required, in what quantities, to produce one unit.

## Inventory and Warehousing

A **Warehouse** is a physical storage facility with a location (address, GPS coordinates), total capacity, and current utilization. Warehouses are organized into **Storage Zones** (e.g., cold storage, hazmat, general).

An **Inventory Record** tracks the quantity of a specific product at a specific warehouse, including lot number, expiration date (for perishables), and reorder point.

**Stock Movement** records the inflow and outflow of inventory: receiving (from supplier), picking (for orders), transfers (between warehouses), and adjustments (for damage, shrinkage).

## Orders and Fulfillment

A **Purchase Order (PO)** is issued by a buyer to a supplier. It contains line items, each specifying a product, quantity, agreed unit price, and requested delivery date. A PO has a status lifecycle: draft → submitted → acknowledged → shipped → received → closed.

A **Sales Order** represents customer demand. It includes customer information, shipping address, line items, and payment terms. Sales orders trigger the fulfillment process.

A **Shipment** is the physical movement of goods. Each shipment has a tracking number, carrier, origin facility, destination, estimated delivery date, and actual delivery date. A shipment contains one or more **Packages**, each with weight and dimensions.

## Quality and Compliance

A **Quality Inspection** evaluates incoming materials or outgoing products against defined specifications. Inspections record the inspector, date, pass/fail result, and any defects found.

A **Defect** is a recorded quality issue with a severity (critical, major, minor), root cause category, and corrective action.

A **Compliance Certificate** attests that a product or facility meets regulatory or industry standards (e.g., FDA approval, CE marking, organic certification).

## Relationships

- A Supplier **provides** Raw Materials and Components.
- A Manufacturer **produces** Finished Goods **using** a Bill of Materials.
- A Purchase Order **is placed with** a Supplier **by** a Manufacturer or Distributor.
- A Warehouse **stores** Inventory Records for Products.
- A Shipment **fulfills** a Sales Order and **is handled by** a Logistics Provider.
- A Quality Inspection **is performed on** Products or Raw Materials.
- A Finished Good **is composed of** Components (as defined by the BOM).
- A Defect **is found during** a Quality Inspection and **affects** a specific Product lot.
- A Compliance Certificate **is issued for** a Product or Facility.
