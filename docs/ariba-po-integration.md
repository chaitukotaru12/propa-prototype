# How does ProPa connect to the PO without disturbing existing systems?

**The question:** "After the contract is executed, procurement raises a purchase order (PO) in Ariba or the ERP. How does ProPa connect to that PO, and do we have to change our systems?"

## The short answer

> ProPa doesn't replace the PO or change how it is created. Procurement raises the PO in Ariba exactly as today: one PO for the SOW. ProPa links that PO number to the signed contract's Digital Contract IDs. Invoices still flow through Ariba against the PO. ProPa reads them, maps each line to its contract line, and gives the PM the evidence for the approval they already make in Ariba.
>
> **Ariba stays the system for POs and payment. ProPa holds the contract-line detail that Ariba doesn't have.**

## The flow

| Step | Where | What happens |
| --- | --- | --- |
| 1. Contract signed | ProPa | The budget grid's Digital Contract IDs are locked in the executed SOW. |
| 2. PO created | Ariba / ERP | Procurement raises the PO as usual, typically one PO line for the whole SOW. |
| 3. Invoice submitted | Ariba | The vendor invoices against the PO number, in its own words, as today. |
| 4. Line check | ProPa | Each invoice line is mapped to its Digital Contract ID and checked against what is left on that line. The PM decides. |
| 5. Payment released | Ariba / ERP | The approved amount is paid through the existing process. |
| 6. Balances updated | ProPa | Paid status flows back, so every contract line's balance stays current. |

## How the connection is made, lightest first

None of these levels changes how POs are created or how vendors invoice.

| Level | How ProPa gets the PO and invoices | Change to existing systems |
| --- | --- | --- |
| **1. Manual link** | After the PO is raised, the procurement team enters the PO number once in ProPa (the "PO number" field in the Streamlit demo). Invoices are uploaded or forwarded to ProPa. | None |
| **2. Report export** | ProPa reads the PO and invoice reports procurement already exports from Ariba or the ERP, and links each PO to its SOW using the reference already in the PO (for example "SOW-01 / ONC-2026-017"). | None; uses existing reports |
| **3. Read-only connection** | ProPa reads POs and invoices directly from Ariba or the ERP through a read-only integration. | IT approves read access; nothing is written to Ariba |
| **4. Two-way (later)** | ProPa sends the PM's decision back as the invoice approval or a comment in Ariba. | Optional, once the sponsor trusts the tool |

Pilots start at level 1 or 2: no IT project, which makes a pilot easy to approve.

## Follow-up questions

**What links the PO to the contract?**
The PO number, recorded once against the SOW. Every invoice already quotes it, so ProPa knows straight away which contract, and which set of Digital Contract IDs, applies.

**Many sponsors raise a single PO line for the whole SOW. Is that a problem?**
No; it is the reason ProPa is useful. With one PO line, a PO-level check only confirms that the total is under the PO value. It cannot see that one budget line has been over-billed while the total still looks fine. ProPa holds the line-level detail itself and maps each invoice line to its Digital Contract ID, so procurement does not need to change how POs are raised.

**Does the vendor have to change anything?**
No. Vendors keep invoicing in Ariba against the same PO. ProPa maps their lines on the sponsor's side using the description, unit price and unit type, and remembers wording the PM has confirmed.

**What happens when there is a change order?**
The executed change order adds or versions Digital Contract IDs in ProPa. Procurement updates the PO value in Ariba as usual, and ProPa picks up the new value the next time the PO is read.

**Can people see the IDs inside Ariba?**
Yes, without any integration. Sponsors usually attach the SOW to the PO already; attaching the tagged SOW instead puts the IDs in Ariba.

**Who approves the invoice?**
The same PM, in the same Ariba approval step as today. ProPa adds the evidence: which contract line each charge belongs to, what is left on it, and what to hold.

**Is our data safe?**
At levels 1 to 3, ProPa only reads data. Approvals and payments stay in the sponsor's existing systems.

---

*ProPa is a prototype on synthetic data. Ariba and SAP are trademarks of their owners; ProPa is not affiliated with them.*
