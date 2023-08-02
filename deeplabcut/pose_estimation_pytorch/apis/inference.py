from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import torch
from deeplabcut.pose_estimation_pytorch.models import PREDICTORS, PoseModel
from deeplabcut.pose_estimation_pytorch.models.detectors import BaseDetector
from deeplabcut.pose_estimation_pytorch.models.predictors import BasePredictor
from deeplabcut.pose_estimation_pytorch.post_processing import (
    rmse_match_prediction_to_gt,
)
from torchvision.transforms import Resize as TorchResize


def get_predictions_bottom_up(
    model: PoseModel, predictor: BasePredictor, images: torch.Tensor
) -> np.array:
    """Gets the predicted coordinates tensor for a bottom_up approach

    Model and images should already be on the same device

    Args:
        model (PoseModel): bottom-up model
        predictor (BasePredictor): predictor used to regress keypoints coordinates and scores
        images (torch.Tensor): input images (should already be normalised and formatted if needed),
                                shape (batch_size, 3, height, width)

    Returns:
        np.array: predictions tensor of shape (batch_size, num_animals, num_keypoints, 3)
    """
    output = model(images)
    shape_image = images.shape
    scale_factor = (
        shape_image[2] / output[0].shape[2],
        shape_image[3] / output[0].shape[3],
    )
    predictions = predictor(output, scale_factor)
    return predictions.cpu().numpy()


def get_predictions_top_down(
    detector: BaseDetector,
    model: PoseModel,
    predictor: BasePredictor,
    top_down_predictor: BasePredictor,
    images: torch.Tensor,
    max_num_animals: int,
    num_keypoints: int,
    resize_object: TorchResize,
) -> np.array:
    """
    TODO probably quite bad design, most arguments could be stored somewhere else
    Gets the predicted coordinates tensor for a bottom_up approach

    Detector, Model and images should already be on the same device

    Args:
        detector (BaseDetector): detector used to detect bboxes, should be in eval mode
        model (PoseModel): pose model
        predictor (BasePredictor): predictor used to regress keypoints coordinates and scores in the cropped images
        top_down_predictor (BasePredictor): Given the bboxes and the cropped keypoints
            coordinates, outputs the regressed keypoints
        images (torch.Tensor): input images (should already be normalised and formatted if needed),
                                shape (batch_size, 3, height, width)
        max_num_animals (int) : maximum number of animals to predict
        num_keypoints (int) : number of keypoints per animal in the dataset
        device (Union[torch.device, str]): device everything should be on

    Returns:
        np.array: predictions tensor of shape (batch_size, num_animals, num_keypoints, 3)
    """
    batch_size = images.shape[0]
    output_detector = detector(images)

    boxes = torch.zeros((batch_size, max_num_animals, 4))
    for b, item in enumerate(output_detector):
        boxes[b][: min(max_num_animals, len(item["boxes"]))] = item["boxes"][
            :max_num_animals
        ]  # Boxes should be sorted by scores, only keep the maximum number allowed
    boxes = boxes.int()
    cropped_kpts_total = torch.full(
        (batch_size, max_num_animals, num_keypoints, 3), -1.0
    )

    for b in range(batch_size):
        for j, box in enumerate(boxes[b]):
            if (box == 0.0).all():
                continue
            cropped_image = images[b][:, box[1] : box[3] + 1, box[0] : box[2] + 1]
            cropped_image = resize_object(cropped_image).unsqueeze(0)
            heatmaps = model(cropped_image)

            scale_factors_cropped = (
                cropped_image.shape[2] / heatmaps[0].shape[2],
                cropped_image.shape[3] / heatmaps[0].shape[3],
            )

            cropped_kpts = predictor(heatmaps, scale_factors_cropped)
            cropped_kpts_total[b, j, :] = cropped_kpts[0, 0]

    final_predictions = top_down_predictor(boxes, cropped_kpts_total)
    return final_predictions.cpu().numpy()


def get_detections_batch(
    detector: BaseDetector,
    images: torch.Tensor,
    max_num_animals: int,
) -> torch.Tensor:
    """Given a batch of images, outputs the predicted bboxes.

    Args:
        detector: detector model
        images: batch of images, shape (batch_size, 3, height, width)
        max_num_animals: maximum number of accepted detections

    Returns:
        The coordinates of the bounding boxes shape (batch_size, max_num_animals, 4)
    """
    batch_size = images.shape[0]

    output_detector = detector(images)

    boxes = torch.zeros((batch_size, max_num_animals, 4))
    for b, item in enumerate(output_detector):
        boxes[b][: min(max_num_animals, len(item["boxes"]))] = item["boxes"][
            :max_num_animals
        ]  # Boxes should be sorted by scores, only keep the maximum number allowed
    boxes = boxes.int()

    return boxes


def get_pose_batch(
    pose_model: PoseModel,
    predictor: BasePredictor,
    cropped_images: torch.Tensor,
) -> torch.Tensor:
    """Given a batch of cropped images, outputs a batch of predicted pose coordinates.
    Coordinates are still in cropped image space and needs to be handled accordingly to
    be back in input space.

    Should only be used for top down with a predictor for single animal

    Args:
        pose_model: pose_estimation model
        predictor: regresses the coordinates of the keypoints inside the cropped images
                Must be a single animal predictor
        cropped_images: Batch of cropped images for the top down pose_estimation

    Returns:
        Tensor of the estimated poses (inside the cropped image), shape (batch_size, num_joints, 3)
    """
    outputs = pose_model(cropped_images)

    scale_factors_cropped = (
        cropped_images.shape[2] / outputs[0].shape[2],
        cropped_images.shape[3] / outputs[0].shape[3],
    )

    # Predictor always returns num_animals as 2nd dimension even for single animal ones
    # Hence the slicing
    poses = predictor(outputs, scale_factors_cropped)[:, 0]

    return poses


def match_predicted_individuals_to_annotations(
    predictions: np.ndarray,
    ground_truth: List[np.ndarray],
    max_individuals: int,
) -> None:
    """
    Uses RMSE to match predicted individuals to frame annotations for a batch of
    frames. This method is preferred to OKS, as OKS needs at least 2 annotated
    keypoints per animal (to compute area)

    The prediction arrays are modified in-place, where the order of elements are
    swapped in 2nd dimension (individuals) such that the keypoints in predictions[b][i]
    is matched to the ground truth annotations of ground_truth[b][i]

    Args:
        predictions: (batch, individual, keypoints, 3) predicted keypoints
        ground_truth: list containing "batch" (individual, keypoints, 2) ground truth
            keypoint arrays
        max_individuals: the maximum number of individuals in a frame
    """
    if max_individuals > 1:
        for b in range(predictions.shape[0]):
            match_individuals = rmse_match_prediction_to_gt(
                predictions[b],
                ground_truth[b],
            )
            predictions[b] = predictions[b][match_individuals]


def resize_batch_predictions(
    predictions: np.ndarray,
    original_sizes: np.ndarray,
    image_shape: Tuple[int, int],
) -> None:
    """
    TODO shifting error when padding

    Converts keypoint coordinates to their values in the original image. Call if the
    image was resized during the image augmentation pipeline.

    Modifies the prediction array in-place.

    Args:
        predictions: (batch, individual, keypoints, 3) predicted keypoints
        original_sizes: shape (batch, 3); the original (w, h, c) for images
        image_shape: the (width, height) for the image given to the model
    """
    for b in range(predictions.shape[0]):
        resizing_factor = (
            (original_sizes[b][0] / image_shape[0]).item(),
            (original_sizes[b][1] / image_shape[1]).item(),
        )
        predictions[b, :, :, 0] = (
            predictions[b, :, :, 0] * resizing_factor[1] + resizing_factor[1] / 2
        )
        predictions[b, :, :, 1] = (
            predictions[b, :, :, 1] * resizing_factor[0] + resizing_factor[0] / 2
        )


def inference(
    dataloader: torch.utils.data.DataLoader,
    model: PoseModel,
    predictor: BasePredictor,
    method: str,
    max_individuals: int,
    num_keypoints: int,
    device: str,
    align_predictions_to_ground_truth: bool,
    images_resized_with_transform: bool,
    detector: Optional[BaseDetector] = None,
) -> np.ndarray:
    """
    Runs inference for a pose estimation model.

    Args:
        dataloader: contains the data to run inference on
        model: the pose estimation model to use for inference
        predictor: predictor used to obtain keypoints from the model output
        method: either `"td"` (top-down) or `"bu"` (bottom-up)
        max_individuals: the maximum number of individuals detected in a frame
        num_keypoints: the number of keypoints per individual
        device: the device on which to run inference
        align_predictions_to_ground_truth: whether to align predictions to ground truth
            individuals in the output predictions (prediction i is closest to ground
            truth individual i)
        images_resized_with_transform: whether the image is resized by the transform
        detector: None when `method="bu"`. The detector to use when `method="td"`.

    Returns:
        shape (num_images, individual, keypoints, 3): the predicted keypoints
    """
    if method.lower() == "td":
        if detector is None:
            raise ValueError(
                f"A detector must be provided when running inference for a top-down "
                f"pose estimator!"
            )
        detector.eval()
        detector.to(device)
    elif method.lower() == "bu":
        if detector is not None:
            raise ValueError(
                f"A detector was provided when running inference for a bottom-up "
                f"which is not possible!"
            )
    else:
        raise ValueError(f"Unknown method: {method}. Choose 'td' or 'bu'.")

    model.eval()
    model.to(device)
    predictor.eval()
    predictor.to(device)

    top_down_predictor = None
    resize_object = None
    if method == "td":
        top_down_predictor = PREDICTORS.build(
            {"type": "TopDownPredictor", "format_bbox": "xyxy"}
        )
        top_down_predictor.eval()
        top_down_predictor.to(device)

        resize_object = TorchResize((256, 256))  # TODO hardcoded 256

    predicted_poses = []
    with torch.no_grad():
        for item in dataloader:
            item["image"] = item["image"].to(device)
            image_shape = item["image"].shape  # b, c, w, h
            if method == "td":
                predictions = get_predictions_top_down(
                    detector=detector,
                    model=model,
                    predictor=predictor,
                    top_down_predictor=top_down_predictor,
                    images=item["image"],
                    max_num_animals=max_individuals,
                    num_keypoints=num_keypoints,
                    device=device,
                    resize_object=resize_object,
                )
            else:
                predictions = get_predictions_bottom_up(
                    model=model,
                    predictor=predictor,
                    images=item["image"],
                )

            if align_predictions_to_ground_truth:
                match_predicted_individuals_to_annotations(
                    predictions=predictions,
                    ground_truth=[
                        kpts.cpu().numpy() for kpts in item["annotations"]["keypoints"]
                    ],
                    max_individuals=max_individuals,
                )

            if images_resized_with_transform:
                original_sizes = torch.stack(item["original_size"], dim=1)
                resize_batch_predictions(
                    predictions=predictions,
                    original_sizes=original_sizes.cpu().numpy(),
                    image_shape=(image_shape[2], image_shape[3]),
                )
            predicted_poses.append(predictions)

    if len(predicted_poses) > 0:
        predicted_poses = np.concatenate(predicted_poses, axis=0)
    else:
        predicted_poses = np.zeros((0, max_individuals, num_keypoints, 3))

    return predicted_poses
