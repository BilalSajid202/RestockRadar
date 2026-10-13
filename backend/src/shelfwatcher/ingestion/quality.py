from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np
import cv2


@dataclass
class QualityResult:
    valid_flag: bool
    quality_score: float
    brightness: float
    blur_variance: float
    identical_ratio: float
    failure_reason: Optional[str] = None


class QualityGate:
    """
    Evaluates image quality based on brightness, Laplacian blur variance,
    and pixel uniformity (context.md Section 9.1).
    """

    def __init__(
        self,
        min_brightness: float = 40.0,
        max_brightness: float = 230.0,
        min_laplacian_var: float = 50.0,
        max_identical_ratio: float = 0.60
    ):
        self.min_brightness = min_brightness
        self.max_brightness = max_brightness
        self.min_laplacian_var = min_laplacian_var
        self.max_identical_ratio = max_identical_ratio

    def evaluate(self, image: np.ndarray) -> QualityResult:
        if image is None or image.size == 0:
            return QualityResult(
                valid_flag=False,
                quality_score=0.0,
                brightness=0.0,
                blur_variance=0.0,
                identical_ratio=1.0,
                failure_reason="Empty or null frame"
            )

        # Convert to grayscale for metric evaluations
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # 1. Mean Brightness (0 - 255)
        mean_brightness = float(np.mean(gray))

        # 2. Laplacian Blur Variance
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # 3. Identical Pixel Ratio (blocked or uniform black/white frame)
        # Check most frequent pixel value frequency
        counts = np.bincount(gray.ravel(), minlength=256)
        identical_ratio = float(np.max(counts) / gray.size)

        # Failure condition checks
        if mean_brightness < self.min_brightness:
            return QualityResult(
                valid_flag=False,
                quality_score=0.1,
                brightness=mean_brightness,
                blur_variance=laplacian_var,
                identical_ratio=identical_ratio,
                failure_reason=f"Frame too dark: mean brightness {mean_brightness:.1f} < {self.min_brightness}"
            )

        if mean_brightness > self.max_brightness:
            return QualityResult(
                valid_flag=False,
                quality_score=0.1,
                brightness=mean_brightness,
                blur_variance=laplacian_var,
                identical_ratio=identical_ratio,
                failure_reason=f"Frame overexposed: mean brightness {mean_brightness:.1f} > {self.max_brightness}"
            )

        if laplacian_var < self.min_laplacian_var:
            return QualityResult(
                valid_flag=False,
                quality_score=0.2,
                brightness=mean_brightness,
                blur_variance=laplacian_var,
                identical_ratio=identical_ratio,
                failure_reason=f"Frame too blurry: Laplacian var {laplacian_var:.1f} < {self.min_laplacian_var}"
            )

        if identical_ratio > self.max_identical_ratio:
            return QualityResult(
                valid_flag=False,
                quality_score=0.1,
                brightness=mean_brightness,
                blur_variance=laplacian_var,
                identical_ratio=identical_ratio,
                failure_reason=f"Frame blocked/blank: {identical_ratio * 100:.1f}% pixels identical > {self.max_identical_ratio * 100:.1f}%"
            )

        # Normalized quality score composite (0.0 to 1.0)
        # Optimal brightness ~ 128
        b_score = 1.0 - abs(mean_brightness - 128.0) / 128.0
        blur_score = min(1.0, laplacian_var / 500.0)
        score = 0.5 * b_score + 0.5 * blur_score

        return QualityResult(
            valid_flag=True,
            quality_score=round(score, 3),
            brightness=round(mean_brightness, 2),
            blur_variance=round(laplacian_var, 2),
            identical_ratio=round(identical_ratio, 3),
            failure_reason=None
        )


default_quality_gate = QualityGate()


def check_quality(image: np.ndarray) -> QualityResult:
    return default_quality_gate.evaluate(image)
