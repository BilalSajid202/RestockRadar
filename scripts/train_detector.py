import os
import sys
import json
import argparse
from datetime import datetime, timezone

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main():
    parser = argparse.ArgumentParser(description="Train and Evaluate YOLOv8 Shelf Detector (Milestone 2)")
    parser.add_argument("--model", type=str, default="yolov8s.pt", help="Base model weights (e.g. yolov8s.pt, yolov8n.pt)")
    parser.add_argument("--epochs", type=int, default=30, help="Number of training epochs")
    parser.add_argument("--imgsz", type=int, default=960, help="Inference image resolution")
    parser.add_argument("--batch", type=int, default=8, help="Batch size")
    parser.add_argument("--device", type=str, default="", help="Device: '0' for GPU or 'cpu'")
    parser.add_argument("--version", type=str, default="v1", help="Detector version identifier")
    args = parser.parse_args()

    data_yaml = os.path.abspath("data/yolo/data.yaml")
    output_dir = os.path.abspath(f"models/detector/{args.version}")
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print(f" Milestone 2: Training YOLOv8 Detector ({args.version})")
    print("=" * 60)
    print(f"[*] Dataset Config: {data_yaml}")
    print(f"[*] Base Weights:   {args.model}")
    print(f"[*] Resolution:     {args.imgsz}x{args.imgsz}")
    print(f"[*] Epochs:         {args.epochs}")

    try:
        from ultralytics import YOLO
    except ImportError:
        print("[!] Package 'ultralytics' is not installed in the current environment.")
        print("    Install via: pip install ultralytics")
        return

    # Initialize model
    model = YOLO(args.model)

    # Train on staged mini-shelf dataset
    print("\n[*] Starting training with data augmentations...")
    results = model.train(
        data=data_yaml,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device if args.device else None,
        project=output_dir,
        name="train_run",
        patience=10,
        save=True,
        exist_ok=True,
        # Augmentations per Section 16: brightness, blur, perspective, mosaic
        hsv_v=0.3,
        perspective=0.0005,
        mosaic=1.0,
        flipud=0.0,
        fliplr=0.5
    )

    # Validate model
    print("\n[*] Evaluating model metrics on validation split...")
    val_metrics = model.val(data=data_yaml, split="val")
    map50 = float(val_metrics.box.map50)
    map50_95 = float(val_metrics.box.map)

    print(f"[OK] Validation mAP@0.5:     {map50:.4f}")
    print(f"[OK] Validation mAP@0.5:0.95: {map50_95:.4f}")

    # Copy best weights to target destination
    best_weights = os.path.join(output_dir, "train_run", "weights", "best.pt")
    target_weights = os.path.join(output_dir, "best.pt")
    if os.path.exists(best_weights):
        import shutil
        shutil.copyfile(best_weights, target_weights)
        print(f"[OK] Best weights saved to: {target_weights}")

    # Update models/registry.json
    registry_path = "models/registry.json"
    registry_data = {"models": []}
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry_data = json.load(f)
        except Exception:
            pass

    model_entry = {
        "model_id": f"detector-{args.version}",
        "kind": "detector",
        "version": args.version,
        "base_model": args.model,
        "metrics": {
            "mAP50": round(map50, 4),
            "mAP50_95": round(map50_95, 4),
            "data_origin": "simulated"
        },
        "path": target_weights,
        "status": "CHAMPION" if map50 >= 0.85 else "CANDIDATE",
        "trained_at": datetime.now(timezone.utc).isoformat()
    }

    registry_data["models"].append(model_entry)
    if model_entry["status"] == "CHAMPION":
        registry_data["champion_detector"] = model_entry["model_id"]
    registry_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry_data, f, indent=2)

    print(f"[OK] Model registered in {registry_path} with status {model_entry['status']}.")


if __name__ == "__main__":
    main()
