# Financial Services Domain Model

## Overview

A financial services organization manages a complex network of entities including customers, accounts, transactions, and financial products. This document describes the core domain model for a retail banking operation.

## Customers

A **Customer** is a person or organization that holds one or more accounts with the institution. Customers are classified into two main subtypes:

- **Individual Customer** — a natural person identified by name, date of birth, national ID, and contact information (email, phone, address). Each individual has a credit score and risk rating.
- **Corporate Customer** — a legal entity identified by company name, registration number, industry sector, and incorporation date. Corporate customers have an assigned relationship manager.

Every customer has a unique Customer ID, an onboarding date, and a KYC (Know Your Customer) verification status that can be "pending", "verified", or "expired".

## Accounts

An **Account** belongs to one or more customers (joint accounts are supported). Each account has an account number, currency, balance, and status (active, dormant, closed, frozen).

Account subtypes include:

- **Checking Account** — a transactional account with an optional overdraft limit. May have an associated debit card.
- **Savings Account** — an interest-bearing account with an annual interest rate and minimum balance requirement.
- **Investment Account** — holds a portfolio of financial instruments. Has a risk profile (conservative, moderate, aggressive) and is managed by an investment advisor.
- **Loan Account** — represents a credit facility with a principal amount, interest rate, term in months, and repayment schedule. Loan accounts are linked to collateral assets.

## Transactions

A **Transaction** records the movement of funds. Every transaction has a transaction ID, timestamp, amount, currency, and status (pending, completed, failed, reversed).

Transaction types include:

- **Deposit** — funds added to an account from an external source.
- **Withdrawal** — funds removed from an account.
- **Transfer** — movement of funds between two accounts (has both a source account and destination account).
- **Payment** — a transfer to a merchant or payee, with a payment reference and merchant category code.
- **Fee** — a charge levied by the institution, linked to a fee schedule.

## Financial Products

A **Financial Product** is an offering provided by the institution. Products have a product code, name, description, and eligibility criteria.

- **Credit Card** — a revolving credit product with a credit limit, APR, reward program, and billing cycle.
- **Mortgage** — a secured loan for property purchase with a loan-to-value ratio, property valuation, and fixed or variable rate type.
- **Insurance Policy** — a risk protection product with coverage type (life, property, auto), premium amount, coverage period, and beneficiary.
- **Mutual Fund** — a pooled investment vehicle with a fund manager, NAV (net asset value), expense ratio, and asset class (equity, fixed income, balanced).

## Relationships

- A Customer **holds** one or more Accounts.
- An Account **contains** Transactions.
- A Customer **subscribes to** Financial Products.
- A Loan Account **is secured by** Collateral (which has a type, valuation, and valuation date).
- A Corporate Customer **has** a Relationship Manager (who is an Employee).
- An Investment Account **is managed by** an Investment Advisor.
- A Transfer Transaction **originates from** a source Account and **is directed to** a destination Account.

## Regulatory Entities

- **Regulatory Body** — an external authority (e.g., SEC, FCA) that issues compliance requirements.
- **Compliance Requirement** — a specific regulation or rule that the institution must follow, with an effective date and jurisdiction.
- A Financial Product **is subject to** Compliance Requirements.
- A Customer's transactions **are monitored by** Anti-Money Laundering (AML) screening processes.

## Risk Management

- **Risk Assessment** — an evaluation of a customer's or account's risk profile, including risk score, assessment date, and risk category (low, medium, high, critical).
- **Fraud Alert** — a flagged suspicious activity with alert type, severity, investigation status, and resolution.
- Risk Assessments **are performed on** Customers and Accounts.
- Fraud Alerts **are triggered by** Transactions.
