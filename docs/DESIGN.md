# Design Decisions

## System Goal

Build a store intelligence platform that combines CCTV analytics and POS data to generate business insights.

---

## Architecture

CCTV Video
↓
YOLOv8 Detection
↓
Multi Object Tracking
↓
Zone Mapping
↓
Dwell Time Analytics
↓
SQLite Storage
↓
FastAPI Services
↓
Streamlit Dashboard

---

## Detection

YOLOv8n was selected because:

- Lightweight
- Fast inference
- Easy integration
- Good person detection performance

---

## Tracking

YOLO tracking mode was used to maintain visitor identities across frames.

Each track ID is treated as a unique visitor.

---

## Zone Mapping

The provided store layout image was used as a reference.

Since exact coordinates were unavailable, business zones were manually mapped based on camera view and layout positioning.

Examples:

- FACE_SHOP_ZONE
- SKINCARE_ZONE
- MAKEUP_ZONE

---

## Data Storage

SQLite was selected because:

- Lightweight
- No infrastructure setup
- Easy local testing
- Suitable for prototype scale

---

## APIs

FastAPI was selected because:

- Fast development
- Automatic Swagger documentation
- Strong Python ecosystem

---

## Dashboard

Streamlit was selected because:

- Minimal code
- Fast dashboard creation
- Suitable for analytics visualization

---

## Business Metrics

Generated metrics include:

- Unique Visitors
- Revenue
- Average Order Value
- Conversion Rate
- Revenue Per Visitor
- Dwell Time