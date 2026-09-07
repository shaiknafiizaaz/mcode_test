"""R+L Carriers BOL / Tenet-EBS deterministic rule engines.

Architecture principle (see README):
    BOL text/image -> information extraction -> structured data
    -> deterministic rule engine -> authoritative M-Code database
    -> validation -> suggested Tenet/EBS entries

The engines NEVER invent M-Codes. When something cannot be
determined safely they return VERIFY status instead of guessing.
"""