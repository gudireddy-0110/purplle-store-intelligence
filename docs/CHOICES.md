# Engineering Choices

## Choice 1: YOLOv8

Selected for fast person detection and tracking support.

Alternative considered:
- Faster R-CNN

Reason not chosen:
- Higher computational cost

---

## Choice 2: SQLite

Selected for simplicity and rapid prototyping.

Alternative considered:
- PostgreSQL

Reason not chosen:
- Additional setup complexity

---

## Choice 3: Manual Zone Mapping

Store layout was provided as an image rather than structured coordinates.

Zones were manually defined using camera views and store layout references.

---

## Choice 4: FastAPI

Selected for API development and automatic documentation.

Alternative considered:
- Flask

Reason not chosen:
- Swagger integration requires additional setup.

---

## Choice 5: Streamlit

Selected for quick business dashboard development.

Alternative considered:
- React Dashboard

Reason not chosen:
- Longer development time.

---

## Tradeoffs

Pros:

- Fast implementation
- Easy deployment
- Modular architecture

Cons:

- Zone boundaries are manually defined
- Visitor re-identification across cameras is not implemented
- Prototype scale database