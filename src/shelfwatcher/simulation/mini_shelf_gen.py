import os
import random
from typing import List, Tuple, Dict
import numpy as np
from PIL import Image, ImageDraw, ImageFont


# 10 SKUs + gap ontology matching data.yaml and context.md
SKU_CATALOG: Dict[int, Dict] = {
    1: {"name": "milk_1l", "color": (230, 240, 255), "accent": (30, 144, 255), "text": "MILK 1L", "aspect": 0.45},
    2: {"name": "yogurt_500g", "color": (245, 245, 255), "accent": (65, 105, 225), "text": "YOGURT", "aspect": 0.8},
    3: {"name": "apple_juice_1l", "color": (200, 240, 200), "accent": (34, 139, 34), "text": "APPLE", "aspect": 0.45},
    4: {"name": "orange_juice_1l", "color": (255, 215, 160), "accent": (255, 140, 0), "text": "ORANGE", "aspect": 0.45},
    5: {"name": "white_bread_400g", "color": (245, 222, 179), "accent": (160, 82, 45), "text": "BREAD", "aspect": 0.7},
    6: {"name": "corn_flakes_375g", "color": (255, 230, 150), "accent": (220, 20, 60), "text": "CEREAL", "aspect": 0.65},
    7: {"name": "cooking_oil_1l", "color": (255, 248, 180), "accent": (218, 165, 32), "text": "OIL 1L", "aspect": 0.4},
    8: {"name": "basmati_rice_1kg", "color": (240, 235, 215), "accent": (46, 139, 87), "text": "RICE 1KG", "aspect": 0.6},
    9: {"name": "tomato_ketchup_500g", "color": (255, 190, 190), "accent": (178, 34, 34), "text": "KETCHUP", "aspect": 0.4},
    10: {"name": "black_tea_400g", "color": (220, 190, 170), "accent": (101, 67, 33), "text": "TEA 400G", "aspect": 0.75},
}


class ShelfSceneGenerator:
    """
    Renders realistic staged mini-shelf images and computes exact YOLO annotations
    for products and empty shelf gaps across distinct recording sessions.
    """

    def __init__(self, img_width: int = 960, img_height: int = 960):
        self.width = img_width
        self.height = img_height

    def generate_scene(
        self,
        session_id: int,
        scene_seed: int,
        gap_prob: float = 0.3
    ) -> Tuple[Image.Image, List[Tuple[int, float, float, float, float]]]:
        """
        Renders a shelf frame with 2 tiers and multiple facings per tier.
        Returns the PIL Image and a list of annotations: (class_id, x_center, y_center, w, h).
        """
        rng = random.Random(scene_seed)

        # Base background - back wall & shelf unit
        bg_brightness = rng.randint(45, 65)
        img = Image.new("RGB", (self.width, self.height), (bg_brightness, bg_brightness, bg_brightness + 5))
        draw = ImageDraw.Draw(img)

        # Shelf structure parameters (2 shelf levels)
        levels = [
            {"shelf_y": int(self.height * 0.48), "depth": 35},
            {"shelf_y": int(self.height * 0.88), "depth": 40}
        ]

        annotations = []
        facings_per_shelf = 5
        slot_width = int((self.width - 120) / facings_per_shelf)

        # Draw shelf racks
        for lvl in levels:
            sy = lvl["shelf_y"]
            depth = lvl["depth"]
            # Shelf bracket / board
            draw.rectangle([40, sy, self.width - 40, sy + depth], fill=(130, 135, 140), outline=(90, 95, 100))
            # Shelf front rail
            draw.rectangle([35, sy + depth - 8, self.width - 35, sy + depth + 4], fill=(180, 185, 190), outline=(100, 105, 110))

        # Assign SKUs to slots based on session layout
        for row_idx, lvl in enumerate(levels):
            sy = lvl["shelf_y"]

            for col_idx in range(facings_per_shelf):
                slot_x1 = 60 + col_idx * slot_width
                slot_x2 = slot_x1 + slot_width - 15

                # Determine slot center and bounds
                slot_cx = (slot_x1 + slot_x2) / 2.0
                slot_w = slot_x2 - slot_x1

                # Decide if this facing is a gap (empty) or occupied
                is_gap = rng.random() < gap_prob

                if is_gap:
                    # Class 0: GAP
                    gap_h = int(self.height * 0.22)
                    gap_y2 = sy + 5
                    gap_y1 = gap_y2 - gap_h
                    gap_cy = (gap_y1 + gap_y2) / 2.0

                    # Render subtle shadow / empty backing
                    draw.rectangle([slot_x1, gap_y1, slot_x2, gap_y2], fill=(bg_brightness - 10, bg_brightness - 10, bg_brightness - 10))
                    # Shelf backing line
                    draw.line([slot_x1 + 5, gap_y2 - 2, slot_x2 - 5, gap_y2 - 2], fill=(70, 70, 70), width=2)

                    # Normalized YOLO bbox: class 0
                    norm_cx = slot_cx / self.width
                    norm_cy = gap_cy / self.height
                    norm_w = slot_w / self.width
                    norm_h = gap_h / self.height
                    annotations.append((0, norm_cx, norm_cy, norm_w, norm_h))

                else:
                    # Deterministic SKU selection per slot based on session & position
                    sku_pool = list(SKU_CATALOG.keys())
                    # Different SKU layout per session to guarantee anti-leakage
                    sku_offset = (session_id * 3 + row_idx * 5 + col_idx) % len(sku_pool)
                    sku_id = sku_pool[sku_offset]
                    sku_info = SKU_CATALOG[sku_id]

                    aspect = sku_info["aspect"]
                    item_w = int(slot_w * rng.uniform(0.85, 0.95))
                    item_h = int(item_w / aspect)
                    item_h = min(item_h, int(self.height * 0.28))

                    item_x1 = int(slot_cx - item_w / 2.0)
                    item_x2 = item_x1 + item_w
                    item_y2 = sy + 3
                    item_y1 = item_y2 - item_h
                    item_cy = (item_y1 + item_y2) / 2.0

                    # Draw 3D package (front face + side edge)
                    base_col = sku_info["color"]
                    acc_col = sku_info["accent"]
                    # Add session lighting fluctuation
                    jitter = rng.randint(-15, 15)
                    face_col = tuple(max(0, min(255, c + jitter)) for c in base_col)

                    # Front face
                    draw.rectangle([item_x1, item_y1, item_x2, item_y2], fill=face_col, outline=(50, 50, 50))
                    # Product header banner
                    banner_h = int(item_h * 0.28)
                    draw.rectangle([item_x1 + 2, item_y1 + 2, item_x2 - 2, item_y1 + banner_h], fill=acc_col)
                    # Label text
                    draw.text((item_x1 + 6, item_y1 + banner_h + 8), sku_info["text"], fill=(20, 20, 20))

                    # Normalized YOLO bbox
                    norm_cx = (item_x1 + item_x2) / (2.0 * self.width)
                    norm_cy = item_cy / self.height
                    norm_w = item_w / self.width
                    norm_h = item_h / self.height
                    annotations.append((sku_id, norm_cx, norm_cy, norm_w, norm_h))

        # Apply slight camera noise and ambient lighting gradient
        img_arr = np.array(img, dtype=np.float32)
        noise = rng.gauss(0, 2)
        # Vertical lighting falloff
        gradient = np.linspace(1.05, 0.90, self.height)[:, None, None]
        img_arr = np.clip(img_arr * gradient + noise, 0, 255).astype(np.uint8)

        final_img = Image.fromarray(img_arr)
        return final_img, annotations


def export_dataset(
    output_base_dir: str = "data/yolo",
    train_count: int = 210,
    val_count: int = 45,
    test_count: int = 45
) -> Dict[str, int]:
    """
    Exports a clean M1 dataset with 300+ images strictly separated by session:
    - Session 1: Train
    - Session 2: Validation
    - Session 3: Test
    """
    gen = ShelfSceneGenerator()
    counts = {"train": 0, "val": 0, "test": 0, "gaps": 0, "items": 0}

    splits = [
        ("train", 1, train_count, 0.25),  # Session 1
        ("val", 2, val_count, 0.35),       # Session 2
        ("test", 3, test_count, 0.40)      # Session 3 (more stockouts/gaps)
    ]

    for split_name, session_id, count, gap_p in splits:
        img_dir = os.path.join(output_base_dir, "images", split_name)
        lbl_dir = os.path.join(output_base_dir, "labels", split_name)
        os.makedirs(img_dir, exist_ok=True)
        os.makedirs(lbl_dir, exist_ok=True)

        for i in range(count):
            seed = session_id * 10000 + i
            img, annotations = gen.generate_scene(session_id=session_id, scene_seed=seed, gap_prob=gap_p)

            filename = f"session{session_id}_shelf_{i:04d}"
            img_path = os.path.join(img_dir, f"{filename}.jpg")
            lbl_path = os.path.join(lbl_dir, f"{filename}.txt")

            img.save(img_path, quality=92)

            with open(lbl_path, "w", encoding="utf-8") as f:
                for cls_id, cx, cy, w, h in annotations:
                    f.write(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")
                    if cls_id == 0:
                        counts["gaps"] += 1
                    else:
                        counts["items"] += 1

            counts[split_name] += 1

    return counts
