from dataclasses import dataclass, field


@dataclass
class MjmlTag:
    name: str
    category: str
    icon: str
    description: str
    default_attributes: dict = field(default_factory=dict)
    droppable_in: list = field(default_factory=list)


MJML_TAGS = [
    # Layout
    MjmlTag("mj-section",   "layout",   "rows",          "Container-Zeile",             {"padding": "10px 0"},                  ["body"]),
    MjmlTag("mj-column",    "layout",   "columns",        "Spalte innerhalb einer Section", {"padding": "0 10px"},              ["mj-section", "mj-group"]),
    MjmlTag("mj-wrapper",   "layout",   "box",            "Umschließt mehrere Sections",  {},                                    ["body"]),
    MjmlTag("mj-group",     "layout",   "object-group",   "Gruppe von Spalten",           {},                                    ["mj-section"]),
    # Content
    MjmlTag("mj-text",      "content",  "type",           "Textblock",                   {"padding": "10px", "font-size": "14px"}, ["mj-column"]),
    MjmlTag("mj-image",     "content",  "image",          "Bild",                        {"padding": "10px", "width": "100%"},    ["mj-column"]),
    MjmlTag("mj-button",    "content",  "cursor-pointer", "Call-to-Action Button",        {"padding": "10px", "background-color": "#333333"}, ["mj-column"]),
    MjmlTag("mj-divider",   "content",  "minus",          "Horizontale Trennlinie",       {"border-width": "1px", "border-color": "#cccccc"}, ["mj-column"]),
    MjmlTag("mj-spacer",    "content",  "space",          "Vertikaler Abstand",           {"height": "20px"},                    ["mj-column"]),
    MjmlTag("mj-table",     "content",  "table",          "HTML-Tabelle",                {"padding": "10px"},                    ["mj-column"]),
    MjmlTag("mj-raw",       "content",  "code",           "Reines HTML",                 {},                                     ["mj-column", "mj-head"]),
    # Advanced
    MjmlTag("mj-hero",      "advanced", "layout-template","Hero-Bild-Section",           {},                                     ["body"]),
    MjmlTag("mj-navbar",    "advanced", "navigation",     "Navigationsleiste",            {},                                    ["mj-section"]),
    MjmlTag("mj-social",    "advanced", "share-2",        "Social-Media-Icons",           {},                                    ["mj-column"]),
    MjmlTag("mj-carousel",  "advanced", "images",         "Bild-Karussell",              {},                                     ["mj-section"]),
    MjmlTag("mj-accordion", "advanced", "chevrons-down",  "Akkordeon-Element",           {},                                     ["mj-column"]),
]

MJML_TAG_MAP: dict[str, MjmlTag] = {t.name: t for t in MJML_TAGS}
