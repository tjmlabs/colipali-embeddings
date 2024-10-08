import base64
from io import BytesIO
from typing import Any, Dict, List, Tuple

import runpod
import torch
from colpali_engine.models import ColQwen2, ColQwen2Processor
from PIL import Image

if torch.cuda.is_available():
    device_map = "cuda"
elif torch.backends.mps.is_available():
    device_map = "mps"
else:
    device_map = None

model_name = "vidore/colqwen2-v0.1"
model = ColQwen2.from_pretrained(
    model_name,
    local_files_only=True,
    cache_dir="models_hub/",
    torch_dtype=torch.bfloat16,
    device_map=device_map,
)


processor = ColQwen2Processor.from_pretrained(
    model_name, local_files_only=True, cache_dir="models_hub/"
)


def encode_image(input_data: List[str]) -> Tuple[List[Dict[str, Any]], int]:
    """
    Compute embeddings for one or more images
    Args:
        input_data is a list of base64 encoded images

    Returns:
        an array of floats representing the embeddings of the input images

    Example in repo: images = [
    Image.new("RGB", (32, 32), color="white"),
    Image.new("RGB", (16, 16), color="black"),
        ]
    """
    # goal is to convert input_data to a list of PIL images
    images = []
    for image in input_data:
        img_data = base64.b64decode(image)
        img = Image.open(BytesIO(img_data))
        img = img.convert("RGB")
        images.append(img)

    batch_images = processor.process_images(images).to(model.device)

    with torch.no_grad():
        image_embeddings = model(**batch_images)

    # Compute total tokens
    seq_length = image_embeddings.shape[1]  # Sequence length dimension
    total_tokens = seq_length * len(input_data)

    results = []
    for idx, embedding in enumerate(image_embeddings):
        embedding = embedding.to(torch.float32).detach().cpu().numpy().tolist()
        result = {"object": "embedding", "embedding": embedding, "index": idx}
        results.append(result)
    return results, total_tokens


def encode_query(queries: List[str]) -> Tuple[torch.Tensor, int]:
    """
        Compute embeddings for one or more text queries.
        Args:
            queries
                A list of text queries.
        Returns:
            an array of floats representing the embeddings of the input queries
        Example in repo: queries = [
        "Is attention really all you need?",
        "Are Benjamin, Antoine, Merve, and Jo best friends?",
    ]
    """
    batch_queries = processor.process_queries(queries)
    # Count tokens
    total_tokens = sum(len(ids) for ids in batch_queries["input_ids"])

    batch_queries = batch_queries.to(model.device)

    with torch.no_grad():
        query_embeddings = model(**batch_queries)

    # we don't need to transform, because we may be scoring and not sending back to the user
    return query_embeddings, total_tokens


def score_documents(
    query_embeddings: List[torch.Tensor], documents: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Score documents against query embeddings and return normalized scores.

    :param query_embeddings: List of query embedding tensors
    :param documents: List of dictionaries containing document id and embeddings
    :return: List of dictionaries with document id and normalized score
    """
    # Convert document embeddings to tensors
    doc_embeddings = [
        torch.tensor(doc["embeddings"], dtype=torch.float32) for doc in documents
    ]

    # convert query_embeds for BFloat to float32
    query_embeddings = query_embeddings.to(torch.float32)

    # Get scores
    raw_scores = processor.score_multi_vector(query_embeddings, doc_embeddings)

    # assert one query
    assert len(raw_scores) == 1, "Only one query is supported"

    # Format the output
    results = []
    for i, score in enumerate(raw_scores[0]):
        results.append(
            {
                "id": documents[i]["id"],
                "score": float(score),
            }
        )

    return results


def handler(job: Dict[str, Any]) -> Dict[str, Any]:
    job_input = job["input"]
    # job_input is a dictionary with the following keys:
    # - input_data: a list of base64 encoded images or text queries
    # - documents: a list of dictionaries containing 'id' and 'embeddings' keys. Only used for scoring
    # - task: a string indicating the task to perform (either 'image' or 'score' or 'query')
    if job_input["task"] == "image":
        embeddings, total_tokens = encode_image(job_input["input_data"])
        return {
            "object": "list",
            "data": embeddings,
            "model": "vidore/colpal-v1.2",
            "usage": {
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens,
            },
        }
    elif job_input["task"] == "query":
        query_embeddings, total_tokens = encode_query(job_input["input_data"])
        results = []
        for idx, embedding in enumerate(query_embeddings):
            embedding = embedding.to(torch.float32).detach().cpu().numpy().tolist()
            result = {"object": "embedding", "embedding": embedding, "index": idx}
            results.append(result)
        return {
            "object": "list",
            "data": results,
            "model": "vidore/colpal-v1.2",
            "usage": {
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens,
            },
        }
    elif job_input["task"] == "score":
        query_embeddings, total_tokens = encode_query(job_input["input_data"])
        # documents is a list of dictionaries containing 'id' and 'embeddings' keys
        # example: documents = [{"id": 0, "embeddings": [[0.1, 0.2, ...], [0.3, 0.4, ...], ...]}, {"id": 1, "embeddings": [[0.5, 0.6, ...], [0.7, 0.8, ...], ...]}]
        documents = job_input["documents"]
        # we want scores to look like this: [{"id": 0, "score": 0.87}, {"id": 1, "score": 0.65}]
        scores = score_documents(query_embeddings, documents)
        return {
            "object": "list",
            "data": scores,
            "model": "vidore/colpal-v1.2",
            "usage": {
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens,
            },
        }
    else:
        raise ValueError(f"Invalid task: {job_input['task']}")


runpod.serverless.start({"handler": handler})
