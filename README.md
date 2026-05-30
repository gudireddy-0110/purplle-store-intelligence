# Purplle Store Intelligence System

## Overview

This project builds a Store Intelligence platform using CCTV video analytics and POS transaction data.

The system detects visitors from store CCTV feeds, tracks movement across zones, calculates dwell time, stores events in SQLite, and exposes business metrics through FastAPI and Streamlit dashboards.

---

## Features

### Computer Vision

- Person Detection using YOLOv8
- Multi Object Tracking
- Visitor Identification
- Zone Mapping
- Dwell Time Analytics

### Data Platform

- SQLite Event Storage
- FastAPI APIs
- Store Metrics
- POS Analytics
- Conversion Rate Analytics

### Dashboard

- Unique Visitors
- Transactions
- Revenue
- Average Order Value
- Conversion Rate

---

## Architecture

CCTV Videos
↓
YOLOv8 Detection
↓
Visitor Tracking
↓
Zone Classification
↓
Dwell Time Calculation
↓
SQLite Database
↓
FastAPI APIs
↓
Streamlit Dashboard

---

## Technology Stack

### Computer Vision

- Python
- OpenCV
- YOLOv8
- Ultralytics

### Backend

- FastAPI
- SQLite

### Analytics

- Pandas
- NumPy

### Dashboard

- Streamlit

---

## APIs

### Health Check

GET

```text
/health
```

### Events

GET

```text
/events
```

### Store Metrics

GET

```text
/stores/{store_id}/metrics
```

### POS Metrics

GET

```text
/pos-metrics
```

---

## Business Metrics

### Visitor Analytics

- Unique Visitors
- Zone Visits
- Dwell Time

### Sales Analytics

- Transactions
- Revenue
- Average Order Value

### Store Intelligence KPIs

- Conversion Rate
- Revenue Per Visitor

---

## Assumptions

- Only person class is tracked.
- Store layout image is used as a visual reference.
- Zones are manually mapped from camera views.
- Each tracked ID is treated as a unique visitor.
- POS transactions are assumed to belong to the same store.

---

## Running the Project

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Start FastAPI

```bash
uvicorn app.main:app --reload
```

### Start Dashboard

```bash
streamlit run dashboard/dashboard.py
```

---

## Project Structure

```text
app/
dashboard/
pipeline/
data/
docs/
tests/
```

---

## Future Improvements

- Real-time Kafka Streaming
- Multi-camera Visitor Re-identification
- Heatmaps
- Queue Analytics
- Product Interaction Analytics
- Recommendation Engine
