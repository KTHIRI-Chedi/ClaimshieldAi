# Fictional motor insurance policy wording for the ClaimShield AI demo (course project).
# Structured as "Part X" / "Clause n.m" so the ingestion chunker splits it clause by clause.
# Amounts (deductible, coverage limit, auto-approval limit) are NOT in this document: they come from the
# policy schedule (policies.csv), as the Solution Design requires ("exact figures come from the database").

TITLE = "ClaimShield Mutual Motor Insurance - Policy Wording"
SUBTITLE = "Fictional document written for the ClaimShield AI course project (ESPRIT, 5DS8). Not a real insurance contract."
VERSION = "Version MW-2026.1 - applies to products motor_comprehensive and motor_third_party"

PARTS = [
    ("Part A - General provisions", "both", [
        ("Clause 1.1", "Products covered by this wording",
         "This wording applies to two products. The motor_comprehensive product covers damage to the insured vehicle "
         "(Part B) and liability to third parties (Part C). The motor_third_party product covers only liability to third "
         "parties (Part C); damage to the insured vehicle itself is not covered under motor_third_party, except glass "
         "breakage when the glass option is shown in the schedule."),
        ("Clause 1.2", "Policy schedule",
         "The policy schedule states the policy number, the product, the period of insurance, the deductible, the "
         "coverage limit per claim and any options. If this wording and the schedule differ on an amount or a date, the "
         "schedule applies."),
        ("Clause 1.3", "Period of insurance",
         "Cover applies only to incidents that occur between the start date and the end date shown in the schedule, "
         "both included, while the policy status is active. An incident that occurs before the start date, after the "
         "end date, or while the policy is suspended or cancelled is not covered."),
        ("Clause 1.4", "Insured vehicle and drivers",
         "Cover applies to the vehicle identified in the schedule, driven by the policyholder or by any person holding a "
         "valid driving licence for that category of vehicle, with the policyholder's permission."),
        ("Clause 1.5", "Deductible",
         "For every claim under Part B, the amount shown as the deductible in the schedule is paid by the policyholder "
         "and deducted from the settlement. No deductible applies to claims under Part C."),
        ("Clause 1.6", "Coverage limit",
         "The insurer's payment for one claim under Part B never exceeds the coverage limit shown in the schedule, "
         "after the deductible."),
    ]),
    ("Part B - Damage to the insured vehicle (motor_comprehensive only)", "motor_comprehensive", [
        ("Clause 2.1", "Collision and accidental damage",
         "The insurer pays for sudden and accidental damage to the insured vehicle caused by a collision with another "
         "vehicle, a fixed object, an animal, or by the vehicle overturning, whether or not a third party is "
         "responsible. This includes damage to bumpers, bonnet, wings, doors, boot or tailgate, lights, grille, mirrors, "
         "radiator and other body or mechanical parts damaged in the incident."),
        ("Clause 2.2", "Vandalism and malicious damage",
         "The insurer pays for damage deliberately caused to the insured vehicle by a third party, including scratched "
         "paintwork, broken mirrors, punctured tyres and broken windows, provided the incident has been reported to the "
         "police within 48 hours and the report reference is supplied with the claim."),
        ("Clause 2.3", "Glass breakage",
         "The insurer pays for the repair or replacement of the windscreen, rear window, side windows and sunroof glass "
         "broken by an external object or an accident. Repair is preferred to replacement when the impact can be "
         "repaired. Glass claims do not reduce any no-claims discount."),
        ("Clause 2.4", "Fire, theft and attempted theft",
         "The insurer pays for damage caused by fire, explosion or lightning, for the theft of the vehicle, and for "
         "damage caused during a theft or an attempted theft, including forced locks and damaged ignition."),
        ("Clause 2.5", "Natural events",
         "The insurer pays for damage caused by storm, hail, flood or falling trees, provided the event is documented by "
         "a weather report or an official notice for the area and date of the incident."),
        ("Clause 2.6", "Repair costs that are covered",
         "Covered repair costs are the replacement parts needed to restore the damaged parts, the labour to remove, fit "
         "and adjust them at a reasonable rate for the region, and the painting of the repaired or replaced panels "
         "including paint and painting materials. Only the parts damaged in the incident are covered."),
        ("Clause 2.7", "Painting limited to the damaged panels",
         "Painting is covered for the panels that were repaired or replaced and, where needed for a colour match, for the "
         "adjacent panels only. Painting of the whole vehicle is not covered unless the damage affects most of its panels."),
        ("Clause 2.8", "Towing and storage",
         "Towing of the vehicle from the place of the incident to the nearest suitable garage, and storage for up to 10 "
         "days, are covered when the vehicle cannot be driven safely after the incident."),
    ]),
    ("Part C - Liability to third parties (both products)", "both", [
        ("Clause 3.1", "Damage to third-party property",
         "The insurer pays the amounts the policyholder is legally liable to pay for damage caused to another person's "
         "vehicle or property by the use of the insured vehicle."),
        ("Clause 3.2", "Bodily injury to third parties",
         "Bodily injury to third parties is handled under the statutory liability cover and is outside the scope of the "
         "automated claims review; such claims are always sent to a human adjuster."),
    ]),
    ("Part D - Exclusions (both products)", "both", [
        ("Clause 4.1", "Wear and tear, mechanical and electrical breakdown",
         "The insurer does not pay for wear and tear, gradual deterioration, rust or corrosion, or mechanical, "
         "electrical or electronic breakdown, unless the breakdown is the direct result of a covered incident."),
        ("Clause 4.2", "Pre-existing damage",
         "Damage that existed before the incident, or before the start date of the policy, is not covered. Signs such as "
         "rust in scratches, faded or flaking paint around the damage, or dirt inside the dents indicate pre-existing "
         "damage and may lead to a partial or total refusal of the claim."),
        ("Clause 4.3", "Damage not related to the incident",
         "Parts that do not appear damaged in the photos of the incident, or whose damage does not match the described "
         "circumstances, are not covered. Repairs of unrelated defects carried out at the same time as the covered repair "
         "are at the policyholder's expense."),
        ("Clause 4.4", "Driver condition and licence",
         "There is no cover under Part B when the driver was under the influence of alcohol or drugs above the legal "
         "limit, did not hold a valid licence, or was driving without the policyholder's permission."),
        ("Clause 4.5", "Excluded uses",
         "There is no cover when the vehicle was used for racing, speed tests, rallies, paid transport of passengers or "
         "goods, or driving lessons, unless the schedule expressly includes that use."),
        ("Clause 4.6", "Intentional damage and fraud",
         "Damage caused intentionally by the policyholder or a driver, and any claim that is exaggerated or supported by "
         "false documents or photos, are not covered. See Clause 5.6."),
        ("Clause 4.7", "Tyres, upgrades and consequential loss",
         "Tyres damaged by braking, punctures or road use alone, upgrades or accessories not fitted by the manufacturer "
         "and not declared in the schedule, loss of use, depreciation and any indirect or consequential loss are not "
         "covered."),
    ]),
    ("Part E - Claims procedure and conditions (both products)", "both", [
        ("Clause 5.1", "Notice of claim",
         "The policyholder must notify the insurer within 5 working days of the incident, with the date, place and a "
         "description of the circumstances. A late notice may lead to refusal if it prevents the insurer from checking "
         "the damage."),
        ("Clause 5.2", "Photos of the damage",
         "The claim must include between 1 and 8 recent photos of the damage showing the whole vehicle and close-ups of "
         "each damaged area. Photos must be taken after the incident and must not have been used in another claim."),
        ("Clause 5.3", "Repair invoice",
         "The claim must include the repair invoice or estimate issued by the garage, listing each part, its quantity "
         "and price, the labour hours and rate, taxes and the total. The invoiced parts must correspond to the damage "
         "visible in the photos."),
        ("Clause 5.4", "Inspection by an expert",
         "The insurer may ask for the vehicle to be inspected by an independent expert before or after the repair. The "
         "policyholder must make the vehicle available within 10 working days of the request."),
        ("Clause 5.5", "Settlement",
         "The insurer pays the covered repair costs, minus the deductible and within the coverage limit, directly to the "
         "garage or to the policyholder on presentation of the paid invoice. Claims below the automatic approval limit "
         "shown in the schedule may be settled without a human review when no warning sign is found."),
        ("Clause 5.6", "Fraud",
         "Any false declaration, falsified invoice, reused or manipulated photo, or exaggeration of the damage leads to "
         "the refusal of the whole claim and may lead to the cancellation of the policy. The insurer may open an "
         "investigation and inform the relevant authorities."),
        ("Clause 5.7", "Frequent claims",
         "The insurer may review the policy at renewal when three or more claims have been made within twelve months."),
    ]),
]
