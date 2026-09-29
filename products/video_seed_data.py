"""Reviewed source data for the public Classei Vimeo channel.

Only ``erp_numbers`` and ``category_slugs`` create product assignments. Entries
marked ``category_description`` or ``manual`` are deliberately imported as
videos without product assignments, so editors can place general films in a
category description or review them later.
"""

CLASSEI_VIMEO_VIDEOS = (
    {
        "vimeo_id": "1018561410",
        "title": "Vergleich herkömmliche Ablage und Classei",
        "disposition": "category_description",
        "reason": "Allgemeiner Systemvergleich; gehört in einen Kategorie-/Informationstext.",
    },
    {
        "vimeo_id": "502531055",
        "title": "Classei Imagefilm 2021",
        "disposition": "category_description",
        "reason": "Allgemeiner Imagefilm ohne eindeutigen Artikelbezug.",
    },
    {
        "vimeo_id": "340139648",
        "title": "Die wiederverwendbare Orga-Mappe Art. 20 44 51",
        "erp_numbers": ("204451",),
        "position": 100,
    },
    {
        "vimeo_id": "241517278",
        "title": "Classata Schrank",
        "erp_numbers": ("730503",),
        "position": 100,
    },
    {
        "vimeo_id": "170149734",
        "title": "Die Blättersicht-Mappe",
        "erp_numbers": ("224453", "224453P"),
        "position": 100,
    },
    {
        "vimeo_id": "158880261",
        "title": "Einleitung Classei Orga-Boxen",
        "disposition": "category_description",
        "reason": "Kategorie-Einleitung; nicht pauschal allen Boxen als Produktvideo zuordnen.",
    },
    {
        "vimeo_id": "152174584",
        "title": "Einleitung Classei Orga-Mappen",
        "disposition": "category_description",
        "reason": "Kategorie-Einleitung; nicht pauschal allen Mappen als Produktvideo zuordnen.",
    },
    {
        "vimeo_id": "152159824",
        "title": "Einleitung Classei Orga-Tabs",
        "disposition": "category_description",
        "reason": "Kategorie-Einleitung; nicht pauschal allen Tabs als Produktvideo zuordnen.",
    },
    {
        "vimeo_id": "85354439",
        "title": "Die Blättersicht-Hülle",
        "erp_numbers": ("224553",),
        "position": 100,
    },
    {
        "vimeo_id": "81796082",
        "title": "Fensterreiter verschieben",
        "erp_numbers": ("204462",),
        "position": 100,
    },
    {
        "vimeo_id": "56894720",
        "title": "Classei-Film Kurzversion",
        "disposition": "category_description",
        "reason": "Allgemeiner Systemfilm ohne eindeutigen Artikelbezug.",
    },
    {
        "vimeo_id": "56743453",
        "title": "Easy-Binding",
        "disposition": "category_description",
        "reason": "Erklärt die Produktgruppe; der richtige Pflegeort ist die Easy-Binding-Kategoriebeschreibung.",
    },
    {
        "vimeo_id": "41014047",
        "title": "Terminverfolgung",
        "erp_numbers": ("900043", "900044", "900047", "900048", "900049", "900050", "900052"),
        "position": 100,
    },
    {
        "vimeo_id": "32567030",
        "title": "Das ZPM = Zeit Projektmanagement",
        "erp_numbers": (
            "466070",
            "584470",
            "586170",
            "626026",
            "806008",
            "806108",
            "806208",
            "806308",
            "816008",
            "818009",
            "910000",
        ),
        "position": 100,
    },
)
