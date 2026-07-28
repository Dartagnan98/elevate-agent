// AUTO-GENERATED — do not edit by hand.
/* eslint-disable */
export const formLibrary: any = {
  "version": 1,
  "province": "BC",
  "board_scope": "All BC boards share the provincial BCREA/BCFSA forms (AOIR, Greater Vancouver, Fraser Valley, Victoria, etc.). Board differences are MLS data + local addenda, not the base forms.",
  "_status": "BC form library seeded from the Elevation Forms Catalog (72 forms). 'fillable' = an auto-fill map exists (scripts/fill-listing-package.py). 'clause_library' links a form to its clause set (only CPS today). Per-agent imported forms live in form-library-custom.json (overlay, never overwritten by rebuild). Other provinces = parallel form-library-<prov>.json with their own base contracts (OREA/AREA), a separate build.",
  "future_provinces": [
    "AB (AREA)",
    "ON (OREA APS)",
    "..."
  ],
  "forms": [
    {
      "id": "disclosure-of-representation-in-trading-services-dorts",
      "name": "Disclosure of Representation in Trading Services (DORTS)",
      "category": "Representation",
      "side": "Both",
      "source": "Webforms",
      "triggered_when": "Always — first signing",
      "notes": "Synonym: Disclosure of Representation",
      "origin": "library",
      "fillable": true,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "multiple-listing-contract-mlc",
      "name": "Multiple Listing Contract (MLC)",
      "category": "Listing Contract",
      "side": "Listing",
      "source": "Webforms",
      "triggered_when": "MLS listing",
      "notes": "",
      "origin": "library",
      "fillable": true,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "exclusive-listing-contract-elc",
      "name": "Exclusive Listing Contract (ELC)",
      "category": "Listing Contract",
      "side": "Listing",
      "source": "Webforms",
      "triggered_when": "Exclusive listing or assignment with advertising restriction",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "authority-to-lease-residential",
      "name": "Authority to Lease – Residential",
      "category": "Listing Contract",
      "side": "Listing",
      "source": "Webforms",
      "triggered_when": "Lease listing only",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "schedule-a-listing",
      "name": "Schedule A (Listing)",
      "category": "Listing Contract",
      "side": "Listing",
      "source": "Webforms",
      "triggered_when": "Listing — services and clauses",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "privacy-notice-consent-pnc",
      "name": "Privacy Notice & Consent (PNC)",
      "category": "Privacy",
      "side": "Both",
      "source": "Webforms",
      "triggered_when": "Always",
      "notes": "",
      "origin": "library",
      "fillable": true,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "politically-exposed-person-form-pep",
      "name": "Politically Exposed Person form (PEP)",
      "category": "FINTRAC",
      "side": "Both",
      "source": "FINTRAC",
      "triggered_when": "When PEP toggle = Yes",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "fintrac-receipt-of-funds-standard",
      "name": "FINTRAC Receipt of Funds (Standard)",
      "category": "FINTRAC",
      "side": "Both",
      "source": "FINTRAC",
      "triggered_when": "Individual signers + deposit to brokerage trust",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "fintrac-3rd-party-form",
      "name": "FINTRAC 3rd Party form",
      "category": "FINTRAC",
      "side": "Both",
      "source": "FINTRAC",
      "triggered_when": "POA / Estate / Corporate signers",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "property-disclosure-statement-pds",
      "name": "Property Disclosure Statement (PDS)",
      "category": "Disclosure",
      "side": "Listing",
      "source": "Webforms",
      "triggered_when": "Residential listings",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "property-no-disclosure-statement-pnds",
      "name": "Property No-Disclosure Statement (PNDS)",
      "category": "Disclosure",
      "side": "Listing",
      "source": "Webforms",
      "triggered_when": "When seller declines PDS",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "title-search-ltsa",
      "name": "Title Search (LTSA)",
      "category": "Title",
      "side": "Both",
      "source": "LTSA",
      "triggered_when": "Always",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "lotr-letter-of-transmittal-receipt",
      "name": "LOTR (Letter of Transmittal & Receipt)",
      "category": "Closing",
      "side": "Both",
      "source": "Webforms",
      "triggered_when": "Confirms deposit",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "lotr-for-client-pid",
      "name": "LOTR for Client + PID",
      "category": "Compliance",
      "side": "Both",
      "source": "BCFSA",
      "triggered_when": "Always — client identification",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "disclosure-of-remuneration",
      "name": "Disclosure of Remuneration",
      "category": "Compliance",
      "side": "Both",
      "source": "Webforms",
      "triggered_when": "Always",
      "notes": "",
      "origin": "library",
      "fillable": true,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "disclosure-of-expected-remuneration-seller",
      "name": "Disclosure of Expected Remuneration (Seller)",
      "category": "Compliance",
      "side": "Listing",
      "source": "Webforms",
      "triggered_when": "BEFORE acceptance — seller side",
      "notes": "",
      "origin": "library",
      "fillable": true,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "lockbox-acknowledgement-consent-release-indemnity",
      "name": "Lockbox Acknowledgement, Consent, Release & Indemnity",
      "category": "Conditional",
      "side": "Listing",
      "source": "Webforms",
      "triggered_when": "If lockbox installed",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "disclosure-of-interest-in-trade-buying-selling",
      "name": "Disclosure of Interest in Trade (Buying/Selling)",
      "category": "Conditional",
      "side": "Both",
      "source": "Webforms",
      "triggered_when": "If family member buying/selling",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "delayed-release-of-offer-drpo",
      "name": "Delayed Release of Offer (DRPO)",
      "category": "Conditional",
      "side": "Listing",
      "source": "Webforms",
      "triggered_when": "If delayed offer presentation",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "co-listing-form-joint-representation",
      "name": "Co-Listing Form – Joint Representation",
      "category": "Conditional",
      "side": "Listing",
      "source": "Webforms",
      "triggered_when": "Co-listing joint",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "co-listing-form-separate-representation",
      "name": "Co-Listing Form – Separate Representation",
      "category": "Conditional",
      "side": "Listing",
      "source": "Webforms",
      "triggered_when": "Co-listing separate",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "disclosure-of-risks-to-unrepresented-parties",
      "name": "Disclosure of Risks to Unrepresented Parties",
      "category": "Conditional",
      "side": "Both",
      "source": "Webforms",
      "triggered_when": "If other side unrepresented",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "mutual-agreement-to-end-a-tenancy",
      "name": "Mutual Agreement to End a Tenancy",
      "category": "Tenanted",
      "side": "Listing",
      "source": "Webforms / RTB",
      "triggered_when": "If selling tenanted property vacant",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "rental-data-input-form",
      "name": "Rental Data Input Form",
      "category": "Lease",
      "side": "Listing",
      "source": "MLS",
      "triggered_when": "Lease listing on MLS",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "full-realtor-mls-printout",
      "name": "Full REALTOR® MLS Printout",
      "category": "Closing",
      "side": "Both",
      "source": "Xposure",
      "triggered_when": "Always (listing) / SOLD version (buyer)",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "buyer-s-agency-exclusive-contract-baec",
      "name": "Buyer's Agency Exclusive Contract (BAEC)",
      "category": "Representation",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Buyer side — BEFORE offer",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "buyer-s-agency-acknowledgement",
      "name": "Buyer's Agency Acknowledgement",
      "category": "Representation",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Buyer side — alternative to BAEC",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "tenant-agency-exclusive-contract",
      "name": "Tenant Agency Exclusive Contract",
      "category": "Representation",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Tenant placement",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "contract-of-purchase-sale-residential",
      "name": "Contract of Purchase & Sale (Residential)",
      "category": "Purchase Contract",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Residential purchase",
      "notes": "",
      "origin": "library",
      "fillable": true,
      "clause_library": "cps-clause-library.json",
      "umbrella": "residential",
      "webforms_template": "A- CPS Residential"
    },
    {
      "id": "contract-of-purchase-sale-strata",
      "name": "Contract of Purchase & Sale (Strata)",
      "category": "Purchase Contract",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Strata purchase",
      "notes": "Skyleigh's webforms skill: cps-strata",
      "origin": "library",
      "fillable": true,
      "clause_library": "cps-clause-library.json",
      "umbrella": "strata",
      "webforms_template": "A- CPS STRATA"
    },
    {
      "id": "contract-of-purchase-sale-manufactured-home-on-rental-site",
      "name": "Contract of Purchase & Sale – Manufactured Home on Rental Site",
      "category": "Purchase Contract",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Mobile in park",
      "notes": "cps-mobile",
      "origin": "library",
      "fillable": true,
      "clause_library": "cps-clause-library.json",
      "umbrella": "mobile",
      "webforms_template": "A- CPS Mobile"
    },
    {
      "id": "contract-of-purchase-sale-bareland-strata-with-mobile",
      "name": "Contract of Purchase & Sale – Bareland Strata with Mobile",
      "category": "Purchase Contract",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Bareland strata mobile",
      "notes": "bareland-strata-mobile",
      "origin": "library",
      "fillable": true,
      "clause_library": "cps-clause-library.json",
      "umbrella": "bare-land-strata",
      "webforms_template": "CPS - Bareland Strata with Mobile"
    },
    {
      "id": "cps-lot",
      "name": "CPS – Lot",
      "category": "Purchase Contract",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Vacant lot purchase",
      "notes": "cps-lot",
      "origin": "library",
      "fillable": true,
      "clause_library": "cps-clause-library.json",
      "umbrella": "lot",
      "webforms_template": "A- CPS LOT"
    },
    {
      "id": "cps-rural",
      "name": "CPS – Rural",
      "category": "Purchase Contract",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Rural / acreage purchase",
      "notes": "cps-rural",
      "origin": "library",
      "fillable": true,
      "clause_library": "cps-clause-library.json",
      "umbrella": "rural",
      "webforms_template": "A- CPS RURAL"
    },
    {
      "id": "cps-new-build",
      "name": "CPS – New Build",
      "category": "Purchase Contract",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Pre-construction",
      "notes": "cps-new-build",
      "origin": "library",
      "fillable": true,
      "clause_library": "cps-clause-library.json",
      "umbrella": "pre-con",
      "webforms_template": "A- CPS NEW BUILD"
    },
    {
      "id": "builder-s-contract-of-purchase-sale",
      "name": "Builder's Contract of Purchase & Sale",
      "category": "Purchase Contract",
      "side": "Buyer",
      "source": "Builder",
      "triggered_when": "Pre-construction",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "builder-fee-agreement",
      "name": "Builder Fee Agreement",
      "category": "Purchase Contract",
      "side": "Buyer",
      "source": "Builder",
      "triggered_when": "Pre-construction",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "disclosure-statement-pre-con",
      "name": "Disclosure Statement (Pre-Con)",
      "category": "Disclosure",
      "side": "Buyer",
      "source": "Builder",
      "triggered_when": "Pre-construction",
      "notes": "7-day rescission triggers when signed + executed",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "assignment-of-contract-of-purchase-sale-new-development",
      "name": "Assignment of Contract of Purchase & Sale – New Development",
      "category": "Assignment",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Buyer-side assignee",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "notice-to-seller-of-assignment-of-terms",
      "name": "Notice to Seller of Assignment of Terms",
      "category": "Assignment",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Buyer-side assignee",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "cps-addendum-i",
      "name": "CPS – Addendum I",
      "category": "Purchase Contract",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Strata + Residential CPS addendum",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "cps-manufactured-home-addendum",
      "name": "CPS – Manufactured Home Addendum",
      "category": "Purchase Contract",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Mobile addendum",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "buyer-s-advisement",
      "name": "Buyer's Advisement",
      "category": "Disclosure",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "Buyer side — highly recommended",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "buyer-s-acknowledgement-of-advice-rights-and-benefits",
      "name": "Buyer's Acknowledgement of Advice, Rights and Benefits",
      "category": "Disclosure",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "If buyer declines recommended subjects",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "subject-removal-conveyancer-form",
      "name": "Subject Removal & Conveyancer Form",
      "category": "Subjects",
      "side": "Buyer",
      "source": "Webforms",
      "triggered_when": "When subjects removed",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "form-k-strata-insurance-certificate",
      "name": "Form K (Strata Insurance Certificate)",
      "category": "Strata",
      "side": "Both",
      "source": "Strata corp",
      "triggered_when": "Strata leases or insurance",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "form-b-strata-information-certificate",
      "name": "Form B (Strata Information Certificate)",
      "category": "Strata",
      "side": "Buyer",
      "source": "Strata corp",
      "triggered_when": "Strata purchase",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "strata-bylaws-rules",
      "name": "Strata Bylaws / Rules",
      "category": "Strata",
      "side": "Buyer",
      "source": "Strata corp",
      "triggered_when": "Strata purchase",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "strata-agm-sgm-minutes-last-2-yrs",
      "name": "Strata AGM/SGM Minutes (last 2 yrs)",
      "category": "Strata",
      "side": "Buyer",
      "source": "Strata corp",
      "triggered_when": "Strata purchase",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "depreciation-report-strata",
      "name": "Depreciation Report (Strata)",
      "category": "Strata",
      "side": "Buyer",
      "source": "Strata corp",
      "triggered_when": "Strata >5 units",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "engineer-s-report-strata",
      "name": "Engineer's Report (Strata)",
      "category": "Strata",
      "side": "Buyer",
      "source": "Strata corp",
      "triggered_when": "If applicable",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "strata-financial-statements-last-2-yrs",
      "name": "Strata Financial Statements (last 2 yrs)",
      "category": "Strata",
      "side": "Buyer",
      "source": "Strata corp",
      "triggered_when": "Strata purchase",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "strata-resale-certificate",
      "name": "Strata Resale Certificate",
      "category": "Strata",
      "side": "Buyer",
      "source": "Strata corp / lawyer",
      "triggered_when": "Strata purchase — BC rules",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "septic-information-request",
      "name": "Septic Information Request",
      "category": "Rural",
      "side": "Both",
      "source": "HP.Admin.Kamloops@interiorhealth.ca",
      "triggered_when": "Rural property",
      "notes": "Form in shared folder",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "well-information-form",
      "name": "Well Information Form",
      "category": "Rural",
      "side": "Both",
      "source": "Province of BC GWELLS",
      "triggered_when": "Rural property",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "wett-certificate-woodstove",
      "name": "WETT Certificate (Woodstove)",
      "category": "Rural",
      "side": "Both",
      "source": "Certified WETT inspector",
      "triggered_when": "Rural with woodstove",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "residential-tenancy-agreement",
      "name": "Residential Tenancy Agreement",
      "category": "Lease",
      "side": "Both",
      "source": "RTB / Webforms",
      "triggered_when": "Tenant placement",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "residential-tenancy-agreement-addendums",
      "name": "Residential Tenancy Agreement Addendums",
      "category": "Lease",
      "side": "Both",
      "source": "Webforms",
      "triggered_when": "Tenant placement",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "rental-application",
      "name": "Rental Application",
      "category": "Lease",
      "side": "Buyer",
      "source": "Landlord BC / template",
      "triggered_when": "Tenant placement",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "agreement-regarding-conflict-of-interest-between-clients",
      "name": "Agreement Regarding Conflict of Interest Between Clients",
      "category": "Conflict",
      "side": "Both",
      "source": "BCFSA",
      "triggered_when": "Dual rep attempt",
      "notes": "Cannot dual rep",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "referral-agreement",
      "name": "Referral Agreement",
      "category": "Referral",
      "side": "Both",
      "source": "Webforms",
      "triggered_when": "Refer-out / receive client",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "disclosure-of-referral-payment",
      "name": "Disclosure of Referral Payment",
      "category": "Referral",
      "side": "Both",
      "source": "Webforms",
      "triggered_when": "Receiving referral payment",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "fee-for-service-agreement",
      "name": "Fee for Service Agreement",
      "category": "Letter of Opinion",
      "side": "Skyleigh side",
      "source": "Webforms",
      "triggered_when": "Letter of Opinion",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "copy-of-valid-power-of-attorney",
      "name": "Copy of Valid Power of Attorney",
      "category": "Authority",
      "side": "Both",
      "source": "Lawyer / client",
      "triggered_when": "POA signing",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "grant-of-probate-grant-of-administration",
      "name": "Grant of Probate / Grant of Administration",
      "category": "Authority",
      "side": "Both",
      "source": "Court / lawyer",
      "triggered_when": "Estate sale (probate complete)",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "will-copy",
      "name": "Will (copy)",
      "category": "Authority",
      "side": "Both",
      "source": "Lawyer",
      "triggered_when": "Estate sale",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "death-certificate",
      "name": "Death Certificate",
      "category": "Authority",
      "side": "Both",
      "source": "Vital Statistics",
      "triggered_when": "Estate sale",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "lawyer-letter-re-estate",
      "name": "Lawyer Letter re: Estate",
      "category": "Authority",
      "side": "Both",
      "source": "Lawyer",
      "triggered_when": "Complex estate",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "corporate-fintrac",
      "name": "Corporate FINTRAC",
      "category": "FINTRAC",
      "side": "Both",
      "source": "FINTRAC",
      "triggered_when": "Corporate seller/buyer",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "annual-filings-corporate",
      "name": "Annual Filings (Corporate)",
      "category": "Authority",
      "side": "Both",
      "source": "Corporate Registry",
      "triggered_when": "Corporate seller/buyer",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "notice-of-articles",
      "name": "Notice of Articles",
      "category": "Authority",
      "side": "Both",
      "source": "Corporate Registry",
      "triggered_when": "Corporate seller/buyer",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    },
    {
      "id": "director-fintrac-per-director",
      "name": "Director FINTRAC (per director)",
      "category": "FINTRAC",
      "side": "Both",
      "source": "FINTRAC",
      "triggered_when": "Corporate signers",
      "notes": "",
      "origin": "library",
      "fillable": false,
      "clause_library": null,
      "umbrella": null,
      "webforms_template": null
    }
  ]
};

export const clauseLibrary: any = {
  "version": 3,
  "side": "buyer",
  "province": "BC",
  "form": "BCREA Contract of Purchase and Sale (CPS)",
  "_status": "v3 (2026-06-25): BUYER-SIDE clauses only. Rebuilt after v2 was found to be contaminated with seller-side wording (accepted offers on Skyleigh's own listings, written by buyers' agents). Every source file here was verified as buyer-side (Forever Real Estate Group / eXp = co-operating/buyer's agent). PENDING SKYLEIGH CONFIRMATION of (1) default clause set per umbrella, (2) preferred wording variant per clause. Every clause needs_confirmation=true; review via cps-clause-review.md.",
  "source_documents": {
    "residential_buyer": [
      "39 Whiteshield Crescent",
      "6402 Furrer Rd (+2 addenda, tenanted+escalation+contractor clauses)",
      "6749 Foothills Dr Vernon (subject-to-sale)",
      "1121 Burgess Way (subject-to-sale w/ 48h notice term)"
    ],
    "strata_buyer": [
      "115-1393 9th Ave (buyer Kyle Winters)"
    ],
    "manufactured_buyer": [
      "49-2401 Ord Rd offer + addendum + pad rental (Brett, Brock Estates park)"
    ]
  },
  "excluded_seller_side": [
    "Greenfield",
    "Arlington",
    "Ellis",
    "Columbia",
    "Dallas (B11)",
    "1153 Lethbridge (all 3 offers - Skyleigh was the seller)"
  ],
  "umbrellas": {
    "residential": {
      "label": "Residential (Freehold)",
      "webforms_template": "A- CPS Residential",
      "card_toggle_match": {
        "property_subtype": "Residential"
      },
      "default_clauses": [
        "financing",
        "inspection",
        "title-review",
        "pds",
        "insurance",
        "bir"
      ]
    },
    "strata": {
      "label": "Strata",
      "webforms_template": "A- CPS STRATA",
      "card_toggle_match": {
        "property_subtype": "Strata"
      },
      "default_clauses": [
        "financing",
        "inspection",
        "title-review",
        "pds",
        "insurance",
        "strata-docs",
        "parking-storage",
        "strata-fee"
      ]
    },
    "mobile": {
      "label": "Manufactured / Mobile (Rental Pad)",
      "webforms_template": "A- CPS Mobile",
      "card_toggle_match": {
        "property_subtype": "Mobile"
      },
      "default_clauses": [
        "financing",
        "pds",
        "title-review",
        "inspection",
        "insurance",
        "bir",
        "park-rules",
        "csa-electrical",
        "pad-rent",
        "schedules-mobile"
      ]
    },
    "rural": {
      "label": "Rural / Acreage",
      "webforms_template": "A- CPS RURAL",
      "card_toggle_match": {
        "property_subtype": "Rural"
      },
      "default_clauses": [
        "financing",
        "inspection",
        "title-review",
        "pds",
        "insurance",
        "bir",
        "rural-septic-inspection",
        "rural-water-potability",
        "rural-water-quantity"
      ],
      "available_extra": [
        "rural-septic-records",
        "rural-well-log"
      ]
    },
    "lot": {
      "label": "Vacant Lot",
      "webforms_template": "A- CPS LOT",
      "card_toggle_match": {
        "property_subtype": "Lot"
      },
      "default_clauses": [
        "financing",
        "title-review",
        "city-file"
      ],
      "_status": "defaults need confirmation; no lot BUYER CPS sampled yet"
    },
    "bare-land-strata": {
      "label": "Bareland Strata (with mobile)",
      "webforms_template": "CPS - Bareland Strata with Mobile",
      "card_toggle_match": {
        "property_subtype": "Bareland-Strata-Mobile"
      },
      "default_clauses": [
        "financing",
        "inspection",
        "title-review",
        "pds",
        "insurance",
        "bir",
        "strata-docs",
        "strata-fee",
        "csa-electrical"
      ],
      "available_extra": [
        "strata-bylaw-notice",
        "strata-special-levy"
      ],
      "_note": "Confirmed from 8-1555 Howe Rd (bareland strata + mobile): STRATA set (strata-docs/fee/bylaw/levy) + the mobile HOME bits (csa-electrical subject, MHR registration) — but NOT the rental-pad clauses (no park consent/pad rent/RTB-10; buyer owns the strata lot). Card must show strata + the home-only mobile clauses (csa-electrical, mhr) for this umbrella, not the park clauses."
    },
    "pre-con": {
      "label": "New Construction / New Build",
      "webforms_template": "A- CPS NEW BUILD",
      "card_toggle_match": {
        "property_subtype": "Pre-Con"
      },
      "default_clauses": [
        "financing",
        "pds",
        "title-review",
        "inspection",
        "insurance",
        "newbuild-occupancy",
        "newbuild-warranty",
        "newbuild-gst",
        "newbuild-deficiency"
      ],
      "_note": "Sourced from A 2969 Gilbert Road (A.Y & Temi Ajani new-build buyer deal). New-construction clauses: occupancy certificate, mandatory 2-5-10 home warranty (Homeowner Protection Act), GST applicable/no rebate, walk-through + deficiency-list holdback. Card shows the new-construction section for this umbrella."
    }
  },
  "clauses": [
    {
      "id": "backup-offer",
      "title": "Backup Offer",
      "section": "buyer-specific",
      "source": "custom",
      "category": "subject",
      "umbrellas": ["residential", "strata", "mobile", "rural", "lot", "bare-land-strata", "pre-con"],
      "needs_confirmation": false,
      "variables": [{ "key": "prior_offer_collapse_date", "type": "date" }],
      "primary_wording": "This Contract of Purchase and Sale is a backup offer, secondary to a prior accepted Contract of Purchase and Sale on the property. This offer is subject to the collapse of the prior accepted Contract, with written confirmation from the Seller to the Buyer, on or before [prior_offer_collapse_date]. Until that confirmation is delivered, the Buyer may terminate this Contract at any time by written notice to the Seller.",
      "primary_source_files": [],
      "variants": []
    },
    {
      "id": "bir",
      "title": "Building Information / Inspection Report (BIR)",
      "section": "common-subject",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "Approving the attached copies of the Survey Certificate (If available) and a Current Building Information Request from the City of Kamloops Building Inspection Division OR TNRD division to be paid by and provided by the Seller. If this condition is waived or declared fulfilled, the attached copies will be incorporated into and form part of this contract.",
      "primary_source_files": [
        "burgess",
        "furrer",
        "whiteshield"
      ],
      "variants": [
        {
          "label": "Schedules incorporated (PDS, Title, BIR)",
          "wording": "Once signed, Property Disclosure Statement, Title and BIR will form part of this Contract as Schedules A, B, AND C .",
          "variables": [],
          "benefit": "both",
          "source_files": [
            "burgess",
            "foothills",
            "furrer"
          ]
        },
        {
          "label": "Subject to Survey Certificate and Building Information Request (BIR)",
          "wording": "Subject to the Buyer receiving and approving all of the following on or before [subject_removal_date]\n\n6) Approving the attached copies of the Survey Certificate (If available) and a Current Building Information Request from the City of Kamloops Building Inspection Division OR TNRD division to be paid by and provided by the Seller. If this condition is waived or declared fulfilled, the attached copies will be incorporated into and form part of this contract.\n\nThe above conditions are for the sole benefit of the Buyer.",
          "variables": [
            {
              "key": "subject_removal_date",
              "type": "date"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "ord-addendum"
          ]
        },
        {
          "label": "Survey Certificate and Building Information Request (BIR) clause",
          "wording": "The Buyer approves the attached copies of the Survey Certificate (If available) and a Current Building Information Request from the City of Kamloops Building Inspection Division OR TNRD division to be paid by and provided by the Seller. If this condition is waived or declared fulfilled, the attached copies will be incorporated into and form part of this contract.",
          "variables": [],
          "benefit": "buyer",
          "source_files": [
            "ninthave"
          ]
        }
      ]
    },
    {
      "id": "city-file",
      "title": "City File / Zoning Bylaw Review",
      "section": "common-subject",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "Obtaining and approving a copy of the City File and the relevant zoning bylaw for the property and uses permitted. Upon acceptance of this offer, the Seller will authorize the Seller's Agent to request, at the Seller's expense a complete City File from the appropriate governing body and upon receipt deliver the documents to the Buyer's Agent at least two days prior to subject removal. Further, the Seller agrees to notify the Buyer's Agent of any changes to the City File until completion. Should the file be outdated and pulled prior to the acceptance of this offer, the Seller's Agent will request any subsequent changes to the file and deliver it to the Buyer's Agent.",
      "primary_source_files": [
        "foothills"
      ],
      "variants": []
    },
    {
      "id": "financing",
      "title": "Financing",
      "section": "common-subject",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "Obtaining a new first mortgage at current bank rates satisfactory to the buyers.",
      "primary_source_files": [
        "burgess",
        "foothills",
        "furrer",
        "whiteshield"
      ],
      "variants": [
        {
          "label": "Subject to New First Mortgage (Financing)",
          "wording": "Subject to the Buyer receiving and approving all of the following on or before [subject_removal_date]\n\n1) Obtaining a new first mortgage at current bank rates satisfactory to the buyers.\n\nThe above conditions are for the sole benefit of the Buyer.",
          "variables": [
            {
              "key": "subject_removal_date",
              "type": "date"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "ord-addendum"
          ]
        },
        {
          "label": "Subject to financing (new first mortgage)",
          "wording": "Subject to the Buyer receiving and approving all of the following on or before [subject_removal_date]\n\nObtaining a new first mortgage at current bank rates satisfactory to the buyers.",
          "variables": [
            {
              "key": "subject_removal_date",
              "type": "date"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "ninthave"
          ]
        }
      ]
    },
    {
      "id": "inspection",
      "title": "Inspection",
      "section": "common-subject",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "inspection_cap",
          "type": "currency"
        }
      ],
      "primary_wording": "At the Buyer's expense, obtaining and approving Professional inspections including but not limited to Home, Termite, Pool / Hot tub, WETT inspection reports against any defects whose cumulative cost of repair exceeds $[inspection_cap] and which reasonably may adversely affect the property's use or value. The Seller will allow access to the property for this purpose on reasonable notice.",
      "primary_source_files": [
        "burgess",
        "foothills",
        "furrer",
        "whiteshield"
      ],
      "variants": [
        {
          "label": "Subject to Home and/or Termite Inspection",
          "wording": "Subject to the Buyer receiving and approving all of the following on or before [subject_removal_date]\n\n4) At the Buyer's expense, obtaining and approving a Professional Home and/or Termite inspection report against any defects whose cumulative cost of repair exceeds $[inspection_defect_threshold] and which reasonably may adversely affect the property's use or value. The Seller will allow access to the property for this purpose on reasonable notice.\n\nThe above conditions are for the sole benefit of the Buyer.",
          "variables": [
            {
              "key": "subject_removal_date",
              "type": "date"
            },
            {
              "key": "inspection_defect_threshold",
              "type": "money"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "ord-addendum"
          ]
        },
        {
          "label": "Subject to professional inspection",
          "wording": "At the Buyer's expense, obtaining and approving professional inspections including but not limited to home, termite, pool, hot tub & wett certification against any defects whose cumulative cost of repair exceeds $[defect_cost_threshold] and which reasonably may adversely affect the property's use or value. The Seller will allow access to the property for this purpose on reasonable notice.",
          "variables": [
            {
              "key": "defect_cost_threshold",
              "type": "currency"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "ninthave"
          ]
        }
      ]
    },
    {
      "id": "insurance",
      "title": "Fire / Property Insurance",
      "section": "common-subject",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "Obtaining approval for fire/property insurance, on terms and at rates, satisfactory to the Buyer.",
      "primary_source_files": [
        "burgess",
        "foothills",
        "furrer",
        "ninthave",
        "whiteshield"
      ],
      "variants": [
        {
          "label": "Subject to Fire/Property Insurance",
          "wording": "Subject to the Buyer receiving and approving all of the following on or before [subject_removal_date]\n\n5) Obtaining approval for fire/property insurance, on terms and at rates, satisfactory to the Buyer.\n\nThe above conditions are for the sole benefit of the Buyer.",
          "variables": [
            {
              "key": "subject_removal_date",
              "type": "date"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "ord-addendum"
          ]
        }
      ]
    },
    {
      "id": "pds",
      "title": "Property Disclosure Statement (PDS)",
      "section": "common-subject",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "pds_date",
          "type": "date"
        }
      ],
      "primary_wording": "Approving the Property Disclosure Statement dated [pds_date] with respect to the information that reasonably may adversely affect the use or value of the property. If approved, such statement will be incorporated into and form part of this contract.",
      "primary_source_files": [
        "burgess",
        "foothills"
      ],
      "variants": [
        {
          "label": "Subject to Property Disclosure Statement Review",
          "wording": "Subject to the Buyer receiving and approving all of the following on or before [subject_removal_date]\n\n2) Approving the Property Disclosure Statement dated [pds_date] with respect to the information that reasonably may adversely affect the use or value of the property. If approved, such statement will be incorporated into and form part of this contract.\n\nThe above conditions are for the sole benefit of the Buyer.",
          "variables": [
            {
              "key": "subject_removal_date",
              "type": "date"
            },
            {
              "key": "pds_date",
              "type": "date"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "ord-addendum"
          ]
        },
        {
          "label": "PDS approval clause",
          "wording": "The Buyer approves the Property Disclosure Statement dated [pds_date] with respect to the information that reasonably may adversely affect the use or value of the property. If approved, such statement will be incorporated into and form part of this contract.",
          "variables": [
            {
              "key": "pds_date",
              "type": "date"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "ninthave"
          ]
        },
        {
          "label": "PDS approval (forming part of contract, second-page variant)",
          "wording": "The Buyers approve Property Disclosure Statement dated [pds_date] with respect to the information that reasonably may adversely affect the use or value of the property. If approved, such statement will be incorporated into and form part of this contract.",
          "variables": [
            {
              "key": "pds_date",
              "type": "date"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "furrer"
          ]
        }
      ]
    },
    {
      "id": "subject-mechanics",
      "title": "Subject Removal / Schedule Mechanics",
      "section": "common-subject",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Buyer and Seller acknowledge having read \"Information About This Contract of Purchase and Sale\" and understood the text explaining the customary cost as stated in Item 6.",
      "primary_source_files": [
        "burgess",
        "foothills",
        "furrer",
        "ninthave",
        "ord-addendum",
        "whiteshield"
      ],
      "variants": [
        {
          "label": "Subject removal umbrella + sole-benefit statement",
          "wording": "Subject to the Buyer receiving and approving all of the following on or before [subject_removal_date]\n\n[numbered conditions]\n\nThe above conditions are for the sole benefit of the Buyer.",
          "variables": [
            {
              "key": "subject_removal_date",
              "type": "date"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "burgess",
            "foothills",
            "furrer",
            "whiteshield"
          ]
        }
      ]
    },
    {
      "id": "title-review",
      "title": "Review of Title",
      "section": "common-subject",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "Searching and approving the attached copy of the title search results. If this condition is waived or declared fulfilled, the attached copy of the title search result will be incorporated into and form part of this contract and the Buyer acknowledges and accepts, despite any other provision in this contract, that upon completion the Buyer will receive title containing any non-financial charge set out in the copy of the title search. At the request of the Buyer's Agent any charges on title will be supplied by the Seller at the Seller's expense.",
      "primary_source_files": [
        "burgess",
        "foothills",
        "ninthave"
      ],
      "variants": [
        {
          "label": "Subject to Title Search Review",
          "wording": "Subject to the Buyer receiving and approving all of the following on or before [subject_removal_date]\n\n3) Searching and approving the attached copy of the title search results. If this condition is waived or declared fulfilled, the attached copy of the title search result will be incorporated into and form part of this contract and the Buyer acknowledges and accepts, despite any other provision in this contract, that upon completion the Buyer will receive title containing any non-financial charge set out in the copy of the title search. At the request of the Buyer's Agent any charges on title will be supplied by the Seller at the Seller's expense.\n\nThe above conditions are for the sole benefit of the Buyer.",
          "variables": [
            {
              "key": "subject_removal_date",
              "type": "date"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "ord-addendum"
          ]
        }
      ]
    },
    {
      "id": "add-buyer",
      "title": "Add Additional Buyer (Section 20A waiver)",
      "section": "buyer-specific",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "additional_buyer_name",
          "type": "text"
        }
      ],
      "primary_wording": "ASSIGNMENT CLAUSE: Notwithstanding Section 20A of the Contract, the Parties agree that the Buyer may, without the consent of the Seller, add [additional_buyer_name] an additional buyer to the contract prior to closing. The Seller's consent does not release the Buyer from liability under this Contract.",
      "primary_source_files": [
        "furrer"
      ],
      "variants": []
    },
    {
      "id": "subject-to-sale",
      "title": "Subject to Sale of Buyer's Property (+ time clause / 48h notice)",
      "section": "buyer-specific",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "buyer_property_address",
          "type": "address"
        },
        {
          "key": "buyer_sale_date",
          "type": "date"
        }
      ],
      "primary_wording": "Subject to the Buyer entering into an unconditional agreement to sell the Buyer's property at [buyer_property_address] on or before [buyer_sale_date]. This condition is for the sole benefit of the Buyer. \"Notice to Buyer's Term\": The Seller upon receipt of another offer may deliver a written notice to the Buyer's agent requiring the Buyer to remove all conditions from the contract within forty-eight (48) hours of the delivery of the notice, not to include Sundays, and Statutory Holidays. If the Buyer fails to remove all the conditions before the expiry of the notice period, the contract will terminate. However, the Buyer and Seller agree that upon the Buyer's conditional acceptance of an offer on their home at [buyer_property_address] and delivery of written notice to the Sellers (or the Seller's agent) of that acceptance and the conditional date on that offer, that the \"Notice to Buyers Term\" above becomes null and void and the subject removal period for the \"Subject to Sale Clause\" changes to 15 days after the delivery of written notice of the acceptance of the offer on the Buyer's home. The Buyers and Sellers further agree that should the buyers not remove the \"Subject to the Sale\" clause within the 15 days and there is no back up offer in place, the \"Subject to the Sale\" clause will revert back to it's original format described above.",
      "primary_source_files": [
        "burgess"
      ],
      "variants": [
        {
          "label": "Subject to sale of buyer's property (becoming unconditional)",
          "wording": "Subject to the Buyer entering into a contract to sell the Buyer's property at [buyer_property_address] and that contract becoming unconditional on or before [buyer_sale_unconditional_date] This condition is for the sole benefit of the Buyer.",
          "variables": [
            {
              "key": "buyer_property_address",
              "type": "address"
            },
            {
              "key": "buyer_sale_unconditional_date",
              "type": "date"
            }
          ],
          "benefit": "buyer",
          "source_files": [
            "foothills"
          ]
        }
      ]
    },
    {
      "id": "tenant-docs",
      "title": "Tenant: Move-In Report & Tenancy Agreement (review)",
      "section": "buyer-specific",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Seller providing copies, and the Buyer approving the copies, of the move-in report and tenancy agreement.",
      "primary_source_files": [
        "furrer"
      ],
      "variants": []
    },
    {
      "id": "tenant-meet-greet",
      "title": "Tenant: Meet & Greet with Tenant",
      "section": "buyer-specific",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "meet_greet_date",
          "type": "date"
        }
      ],
      "primary_wording": "The Seller agrees to arrange a meet and greet for the Buyer & the Tenant on or before [meet_greet_date].",
      "primary_source_files": [
        "furrer"
      ],
      "variants": []
    },
    {
      "id": "tenant-notice-vacate",
      "title": "Tenant: Landlord's Notice to Vacate (s.49 RTA)",
      "section": "buyer-specific",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Seller will give legal notice to the Tenant to vacate the premise, [upon Full Condition Removal but only if the Seller receives] the appropriate written request from the Buyer to give such notice in accordance with the requirements of section 49 of the Residential Tenancy Act.",
      "primary_source_files": [
        "furrer"
      ],
      "variants": []
    },
    {
      "id": "tenant-rent-credit",
      "title": "Tenant: One Month Free Rent Credit",
      "section": "buyer-specific",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Seller agrees to provide the tenants one months free rent to the Buyer via the statement of adjustments as per the residential tenacy act.",
      "primary_source_files": [
        "furrer"
      ],
      "variants": []
    },
    {
      "id": "tenant-warranty",
      "title": "Tenant: Tenancy Warranty (rent, deposit, term)",
      "section": "buyer-specific",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "tenant_name",
          "type": "text"
        },
        {
          "key": "monthly_rent",
          "type": "currency"
        },
        {
          "key": "security_deposit",
          "type": "currency"
        }
      ],
      "primary_wording": "The Seller warrants that [tenant_name] is a MONTH TO MONTH TENANT ; the monthly rent is $ [monthly_rent]; payable on THE FIRST OF THE MONTH a security deposit of $ [security_deposit].",
      "primary_source_files": [
        "furrer"
      ],
      "variants": []
    },
    {
      "id": "rural-septic-inspection",
      "title": "Septic / Sewer System Inspection",
      "section": "rural",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "subject_removal_date",
          "type": "date"
        }
      ],
      "primary_wording": "Subject to the Buyer, at the Buyer's expense, obtaining and approving an inspection of the on-site sewerage / septic disposal system serving the property by a qualified professional on or before [subject_removal_date]. This condition is for the sole benefit of the Buyer.",
      "primary_source_files": [
        "bcrea-standard"
      ],
      "variants": []
    },
    {
      "id": "rural-septic-records",
      "title": "Septic Records (Interior Health)",
      "section": "rural",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "subject_removal_date",
          "type": "date"
        }
      ],
      "primary_wording": "Subject to the Buyer obtaining and approving the on-site sewage system records for the property (including any filing, permits, as-built and maintenance records) from Interior Health on or before [subject_removal_date]. This condition is for the sole benefit of the Buyer.",
      "primary_source_files": [
        "bcrea-standard"
      ],
      "variants": []
    },
    {
      "id": "rural-water-potability",
      "title": "Water Potability Test",
      "section": "rural",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "subject_removal_date",
          "type": "date"
        }
      ],
      "primary_wording": "Subject to the Buyer, at the Buyer's expense, obtaining and approving a potability test confirming the water supply serving the property is safe for human consumption on or before [subject_removal_date]. This condition is for the sole benefit of the Buyer.",
      "primary_source_files": [
        "bcrea-standard"
      ],
      "variants": []
    },
    {
      "id": "rural-water-quantity",
      "title": "Water Quantity & Quality (Flow)",
      "section": "rural",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "subject_removal_date",
          "type": "date"
        }
      ],
      "primary_wording": "Subject to the Buyer, at the Buyer's expense, obtaining and approving a test confirming the quantity and quality (flow rate) of the water supply serving the property is satisfactory to the Buyer on or before [subject_removal_date]. This condition is for the sole benefit of the Buyer.",
      "primary_source_files": [
        "bcrea-standard"
      ],
      "variants": []
    },
    {
      "id": "rural-well-log",
      "title": "Well Log / Well Record",
      "section": "rural",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "subject_removal_date",
          "type": "date"
        }
      ],
      "primary_wording": "Subject to the Buyer obtaining and approving the well record / well log for the property (including well depth, flow rate, and construction details) on or before [subject_removal_date]. This condition is for the sole benefit of the Buyer.",
      "primary_source_files": [
        "bcrea-standard"
      ],
      "variants": []
    },
    {
      "id": "newbuild-deficiency",
      "title": "New Construction: Walk-Through & Deficiency List (Holdback)",
      "section": "new-construction",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "pre-con"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Buyer and an authorized representative of the Seller will jointly conduct a walk-through inspection of the property no later than 7 days before the Completion Date. The parties will, immediately after completion of the walk-through inspection, complete a deficiency list of mutually agreed upon items that are to be remedied by the Seller (the \"Deficiency List\"). The Deficiency List, which will form part of this contract, will identify the deficiencies and include a mutually agreed upon value for each of the deficiencies to be remedied. Both parties will sign, date and retain a copy of the Deficiency List. The quality of work and materials used to correct the deficiencies will be equal to or better than that of the surrounding construction. In the event that the deficiencies are not rectified 3 days prior to completion, the Buyer's conveyancer will hold back from the sale proceeds the amount specified for any uncorrected deficiency until all the deficiencies specified on the Deficiency List are completed, and will place this holdback in the Buyer's Conveyancer's trust account. The Seller agrees that if the conveyance of the Property has been completed and any of the specified deficiencies have not been corrected, the Buyer's conveyancer will retain the specified holdback until the Seller corrects the deficiencies, which shall not be later than 30 days after the Completion Date. The Seller agrees that if the deficiencies have not been corrected by the later date, the Buyer's conveyancer may release the balance of the holdback to the Buyer and the Buyer may correct the deficiencies himself/herself. Any dispute concerning the identification and pricing of deficiencies, the rectification of the deficiencies, and release of the holdback will be settled by arbitration under the British Columbia Arbitration Act at the expense of the Seller.",
      "primary_source_files": [
        "gilbert"
      ],
      "variants": []
    },
    {
      "id": "newbuild-gst",
      "title": "New Construction: GST Applicable (No Rebate)",
      "section": "new-construction",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "pre-con"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Buyer acknowledges that GST is applicable on this property and there is no tax rebate available.",
      "primary_source_files": [
        "gilbert"
      ],
      "variants": []
    },
    {
      "id": "newbuild-occupancy",
      "title": "New Construction: Occupancy Certificate",
      "section": "new-construction",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "pre-con"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "municipality",
          "type": "text"
        }
      ],
      "primary_wording": "It is a fundamental term of this contract that the Seller must have finished all work, and delivered to the Buyer by the Completion Date, an unconditional [municipality] Occupancy Certificate or other evidence satisfactory to the Buyer that the construction is finished.",
      "primary_source_files": [
        "gilbert"
      ],
      "variants": []
    },
    {
      "id": "newbuild-warranty",
      "title": "New Construction: Mandatory Home Warranty (2-5-10)",
      "section": "new-construction",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "pre-con"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "It is a fundamental term of this contract that the mandatory warranty insurance coverage required pursuant to the Homeowner Protection Act be provided.",
      "primary_source_files": [
        "gilbert"
      ],
      "variants": []
    },
    {
      "id": "parking-storage",
      "title": "Parking Stall / Storage Locker",
      "section": "strata",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "Subject to the Buyer verifying the parking stalls\n\nThe above conditions are for the sole benefit of the Buyer.",
      "primary_source_files": [
        "ninthave"
      ],
      "variants": []
    },
    {
      "id": "strata-bylaw-notice",
      "title": "Strata: Seller Notice of Bylaw/Rule Change",
      "section": "strata",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Seller will notify the Buyer before the completion date of any notice of a resolution to amend the bylaws or rules of the strata corporation, or the bylaws or rules of a section to which the strata lot belongs, or any amendment to such bylaws or rules, that the Seller has not previously disclosed to the Buyer.",
      "primary_source_files": [
        "ninthave"
      ],
      "variants": []
    },
    {
      "id": "strata-docs",
      "title": "Review of Strata Documents (Form B, depreciation report, CRF, bylaws, minutes, financials)",
      "section": "strata",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "strata_minutes_start_date",
          "type": "date"
        },
        {
          "key": "strata_minutes_end_date",
          "type": "date"
        }
      ],
      "primary_wording": "Receiving and approving the following documents with respect to information that reasonably may adversely affect the use or value of the strata lot, including any bylaw, item of repair or maintenance, special levy, judgment or other liability, whether actual or potential:\n* A current Form 'B' Information Certificate attaching the strata corporation's rules, current budget and the developer's Rental Disclosure statement, if any;\n* Seller to supply Contingency Reserve Fund report and Depreciation Report\n* A copy of the registered strata plan, any amendments to the strata plan, and any resolutions dealing with changes to common property;\n* The current bylaws and financial statements of the strata corporation, and any section to which the strata corporation lot belongs; and\n* The minutes of any meeting held between the period from [strata_minutes_start_date]- [strata_minutes_end_date] by the strata council, and by the members in annual, extraordinary or special general meetings, and by the members or the executive of any section to which the strata lot belongs.\n*Immediately upon acceptance of this offer or counter-offer, the Seller will authorize the (Seller's) agent, to request, at the (Seller's) expense, complete copies of the documents listed above from the strata corporation or other source and to immediately, upon receipt, deliver the documents to the Buyer (or the Buyer's agent)",
      "primary_source_files": [
        "ninthave"
      ],
      "variants": []
    },
    {
      "id": "strata-fee",
      "title": "Strata Fee Confirmation",
      "section": "strata",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "monthly_strata_fee",
          "type": "currency"
        }
      ],
      "primary_wording": "Seller confirms the monthly strata fee is $[monthly_strata_fee].",
      "primary_source_files": [
        "ninthave"
      ],
      "variants": []
    },
    {
      "id": "strata-special-levy",
      "title": "Strata: Special Levy Credit / Holdback",
      "section": "strata",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Seller will promptly deliver a copy of the relevant resolution or notice of resolution to the Buyer. If a special levy is approved before the completion date, the seller shall credit the buyer with the entire portion of the special levy that the buyer is obligated to pay under the Strata Property Act and the Seller hereby directs the buyer's lawyer or notary public to hold back such credit from the sale proceeds and to remit it to the strata corporation.",
      "primary_source_files": [
        "ninthave"
      ],
      "variants": []
    },
    {
      "id": "csa-electrical",
      "title": "CSA / Electrical / BC Safety Authority",
      "section": "manufactured",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "mobile"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "Receiving the BC Safety Authority approval and electrical number for all the additions and/or alterations done to the property following the original CSA approval.",
      "primary_source_files": [
        "ord-addendum"
      ],
      "variants": []
    },
    {
      "id": "pad-rent",
      "title": "Pad Rent Acknowledgement",
      "section": "manufactured",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "mobile"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "pad_rental_amount",
          "type": "money"
        }
      ],
      "primary_wording": "Buyer is aware and accepts the month pad rent is $[pad_rental_amount].",
      "primary_source_files": [
        "ord-addendum"
      ],
      "variants": []
    },
    {
      "id": "park-rules",
      "title": "Manufactured Park Rules & Regulations",
      "section": "manufactured",
      "source": "library",
      "category": "subject",
      "umbrellas": [
        "mobile"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "park_name",
          "type": "text"
        }
      ],
      "primary_wording": "Buyers receiving copies of the rules and regulations of [park_name] mobile home park and acknowledges and accepts them.",
      "primary_source_files": [
        "ord-addendum"
      ],
      "variants": []
    },
    {
      "id": "schedules-mobile",
      "title": "Schedules Incorporation — mobile (PDS, Title, BIR, Rules)",
      "section": "manufactured",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "mobile"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "Once signed, the Property Disclosure Statement, Title, BIR and Rules and Regulations will form part of this Contract as Schedules A, B, C & D.",
      "primary_source_files": [
        "ord-addendum"
      ],
      "variants": []
    },
    {
      "id": "appliances",
      "title": "Appliance / Equipment Working Order",
      "section": "standard-clause",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Sellers agree the appliances will be in proper working order as of the possession date.",
      "primary_source_files": [
        "burgess",
        "foothills",
        "furrer"
      ],
      "variants": [
        {
          "label": "Appliances in Working Order on Possession",
          "wording": "The Seller agrees that all appliances included in the purchase of the property are to be in proper working order as of the Possession date.",
          "variables": [],
          "benefit": "buyer",
          "source_files": [
            "ord-addendum"
          ]
        },
        {
          "label": "Appliances working order clause",
          "wording": "The Sellers agree the appliances will be in the same working order on the possession date as they were found on the inspection date.",
          "variables": [],
          "benefit": "buyer",
          "source_files": [
            "ninthave"
          ]
        }
      ]
    },
    {
      "id": "cleaning-moveout",
      "title": "Seller Cleaning / Move-Out Obligations",
      "section": "standard-clause",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Buyer & Seller agree the Seller will leave the home in a clean and tidy manner upon possession.",
      "primary_source_files": [
        "burgess",
        "foothills"
      ],
      "variants": [
        {
          "label": "Clean and tidy / receipts on completion clause",
          "wording": "The Buyer & Seller agree the Seller will leave the home in a clean and tidy manner on or before completion. Once completed the Seller will provide receipts to the Buyer promptly.",
          "variables": [],
          "benefit": "buyer",
          "source_files": [
            "ninthave"
          ]
        },
        {
          "label": "Seller to Leave Home Clean and Tidy",
          "wording": "The Seller agrees to leave the home in a clean and tidy manner upon possession.",
          "variables": [],
          "benefit": "buyer",
          "source_files": [
            "ord-addendum"
          ]
        }
      ]
    },
    {
      "id": "force-majeure",
      "title": "Force Majeure / Fire-Flood Extension",
      "section": "standard-clause",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [
        {
          "key": "radius_km",
          "type": "text"
        }
      ],
      "primary_wording": "FORCE MAJEURE: If either party, despite its best efforts, is delayed from completing the transaction due to: acts of God, landslide, flood, tempest, washout, fire, lightning, disaster, earthquake, storm, epidemic, quarantine, or civil disturbance (an \"Event\") within a [radius_km]-kilometre radius of the Property, then the affected party's solicitor shall provide notice (the \"Force Majeure Notice\") to the other party's solicitor of such Event no more than three (3) business days prior to the Completion date and no later than noon on the Completion Date. Upon receipt of the Force Majeure Notice, the Completion, Possession and Adjustment Dates shall be extended one time to the first business day which occurs thirty (30) days following the Force Majeure Notice and time shall remain of the essence. The parties are advised to seek legal advice regarding how this clause may affect any related transactions that are closing on the original completion date.",
      "primary_source_files": [
        "bcrea-standard"
      ],
      "variants": []
    },
    {
      "id": "gst",
      "title": "GST Treatment",
      "section": "standard-clause",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Buyer has been advised to seek independent Legal and Accounting advice pertaining to the above noted property regarding any and all applied taxes and levies including GST.",
      "primary_source_files": [
        "foothills",
        "furrer",
        "ninthave",
        "ord-addendum",
        "whiteshield"
      ],
      "variants": []
    },
    {
      "id": "hot-water-tank",
      "title": "Hot Water Tank Replacement",
      "section": "standard-clause",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "residential"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "Buyer and Seller agree the Seller will have the hot water tank professionally replaced at the Seller's expense if the hot water tank is found to be older than 10 years during the home inspection. Receipts to be provided to the Buyer upon completion of replacement.",
      "primary_source_files": [
        "howe"
      ],
      "variants": []
    },
    {
      "id": "measurements",
      "title": "Dimensions / Measurements Approximate",
      "section": "standard-clause",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Buyer Accepts that all measurements provided are approximate and that they have verified any measurements that may be of importance to them.",
      "primary_source_files": [
        "burgess",
        "foothills",
        "furrer",
        "ninthave",
        "ord-addendum",
        "whiteshield"
      ],
      "variants": []
    },
    {
      "id": "schedules",
      "title": "Incorporation of Documents as Schedules",
      "section": "standard-clause",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "Once signed, Property Disclosure Statement, Title and BIR will form part of this Contract as Schedules A, B, AND C .",
      "primary_source_files": [
        "ninthave"
      ],
      "variants": []
    },
    {
      "id": "title-charge-ack",
      "title": "Title / Charge Acknowledgement (standing clause, not the subject)",
      "section": "standard-clause",
      "source": "library",
      "category": "clause",
      "umbrellas": [
        "mobile",
        "residential",
        "strata"
      ],
      "needs_confirmation": false,
      "variables": [],
      "primary_wording": "The Buyer acknowledges and accepts that on Completion the Buyer will receive title containing, in addition to any encumbrance referred to in Clause 9 (TITLE) of this contract, any non-financial charge set out in the copy of the title search results that is attached to and forms part of this contract.",
      "primary_source_files": [
        "burgess",
        "foothills",
        "furrer",
        "ninthave",
        "ord-addendum",
        "whiteshield"
      ],
      "variants": []
    }
  ]
};
