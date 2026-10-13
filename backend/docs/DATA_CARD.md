# DATA CARD: Restock Radar (Shelf Watcher) Dataset

## 1. Dataset Overview
- **Dataset Name:** Restock Radar Mini-Shelf Benchmark (M1)
- **Version:** 1.0.0
- **Release Date:** 2026-10-07
- **Primary Domain:** Retail shelf object detection, gap recognition, and inventory tracking.
- **Data Origin Types:** 
  - `real_images`: Mini-shelf manual captures (phone camera, 8–10 items).
  - `simulated`: Synthetically rendered shelf configurations with controlled lighting, depleting facings, and empty slots.
  - `public_dataset`: Retail benchmarks reference (SKU-110K, Grocery Store Dataset) for cross-domain transfer.

---

## 2. Class Ontology & Annotation Standard

The ontology defines 12 discrete detection classes with `data/yolo/data.yaml` as the single source of truth.

| Class ID | Class Name | Description | Role |
|---|---|---|---|
| `0` | `gap` | Empty facing on shelf where an item should reside | Out-of-Stock / Planogram mismatch |
| `1` | `milk_1l` | Dairy milk 1-liter bottle/carton | Target SKU (Habib Dairy) |
| `2` | `yogurt_500g` | Packaged yogurt tub 500g | Target SKU (Habib Dairy) |
| `3` | `apple_juice_1l` | Apple fruit juice box 1L | Target SKU (National Foods) |
| `4` | `orange_juice_1l` | Orange fruit juice box 1L | Target SKU (National Foods) |
| `5` | `white_bread_400g` | Sliced bread loaf 400g | Target SKU (National Foods) |
| `6` | `corn_flakes_375g` | Cereal box 375g | Target SKU (National Foods) |
| `7` | `cooking_oil_1l` | Cooking oil bottle 1L | Target SKU (National Foods) |
| `8` | `basmati_rice_1kg` | Packaged Basmati rice pouch 1kg | Target SKU (National Foods) |
| `9` | `tomato_ketchup_500g` | Squeeze bottle tomato ketchup 500g | Target SKU (National Foods) |
| `10` | `black_tea_400g` | Loose black tea box 400g | Target SKU (National Foods) |
| `11` | `person` | Human body / customer in aisle | Privacy blurring only |

### Format: YOLOv8 Bounding Box
Each annotation file contains one row per object:
```text
<class_id> <x_center> <y_center> <width> <height>
```
All bounding box coordinates are normalized in the range $[0.0, 1.0]$ relative to image dimensions.

---

## 3. Data Split Strategy (Anti-Leakage)
To prevent spatial and visual autocorrelation leakage:
- **Partitioning Unit:** Split strictly by **Arrangement Session** (not random frame shuffling).
  - **Train (Session 1):** 70% of frames (~210 images). Standard planogram layouts under daylight and bright warm indoor illumination.
  - **Validation (Session 2):** 15% of frames (~45 images). Alternate SKU ordering and partial gap patterns under varied camera elevation.
  - **Test (Session 3):** 15% of frames (~45 images). Completely separate arrangement session with edge cases (heavy gaps, misplaced items, lighting shifts).

---

## 4. Visual & Environmental Conditions
- **Resolution:** 960x960 (standard YOLO inference scale; tiling applied for panoramic shelves).
- **Lighting Variants:** Daylight (5500K), Warm Fluorescent (3000K), and Dim Ambient (<40 lux flagged by quality gate).
- **Occlusion & Depletion States:**
  - Full capacity (100% fill rate).
  - Partial depletion (50–80% fill rate).
  - Critical stockout (<30% fill rate with prominent `gap` labels).
  - Misplaced item state (SKU placed in incorrect planogram facing).

---

## 5. Privacy, Ethics & Governance
- **Zero Face Recognition:** Strictly no biometric identification.
- **Privacy Filter (`privacy.py`):** Detections of class `11` (`person`) trigger automated Gaussian blurring across the entire bounding box before saving or displaying frames.
- **Honesty in Reporting:** All reported evaluation metrics must be partitioned and explicitly tagged by data origin: `real_images`, `public_dataset`, or `simulated`.
