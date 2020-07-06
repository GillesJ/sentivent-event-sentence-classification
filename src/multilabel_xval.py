#!/usr/bin/env python3
"""
multilabel_xval
sentivent_event_sentence_classification 
12/18/19
Copyright (c) Gilles Jacobs. All rights reserved.  
"""
import matplotlib.pyplot as plt
from simpletransformers.classification import MultiLabelClassificationModel
import pandas as pd
import numpy as np
from pathlib import Path
import settings
from ast import literal_eval
import json
import operator
from functools import reduce
from sklearn.model_selection import GroupKFold


def train_eval(train_df, eval_df, output_dirp):
    """
    Train and eval test a model
    :param train_df:
    :param eval_df:
    :param output_dirp:
    :return:
    """
    print(train_df.head())

    # Define model
    model = MultiLabelClassificationModel(
        settings.MODEL_SETTINGS["model_type"],
        settings.MODEL_SETTINGS["model_name"],
        num_labels=num_labels,
        args=settings.MODEL_SETTINGS["train_args"],
    )

    # Write train
    Path(output_dirp).mkdir(parents=True, exist_ok=True)
    train_fp = Path(output_dirp) / "trainset.tsv"
    train_df.to_csv(train_fp, sep="\t", index=False)

    # reload train for testing
    train_df = pd.read_csv(train_fp, sep="\t", converters={"labels": literal_eval})
    # write and reload eval set for testing
    eval_fp = Path(output_dirp) / "testset.tsv"
    eval_df.to_csv(eval_fp, sep="\t", index=False)
    eval_df = pd.read_csv(eval_fp, sep="\t", converters={"labels": literal_eval})

    # Set tensorflow_dir in model args to run dir
    model.args["tensorboard_dir"] = Path(output_dirp) / "tensorboard/"
    model.args["cache_dir"] = (
        Path(output_dirp) / "cache/"
    )  # to ensure no weights are shared
    model.args["output_dir"] = output_dirp  # is redundant

    # Train the model
    print(f"Training model with args: {model.args}")
    model.train_model(train_df, output_dir=output_dirp)

    # Evaluate the model on eval set
    result, model_outputs, _ = model.eval_model(eval_df)

    # Write model result and outputs
    eval_df["y_pred"] = model_outputs.tolist()
    predictions_fp = Path(output_dirp) / "testset_with_predictions.tsv"
    eval_df.to_csv(predictions_fp, sep="\t", index=False)

    with open(Path(output_dirp) / "result.json", "wt") as result_out:
        json.dump(result, result_out)

    return result, model_outputs


pd.options.mode.chained_assignment = None
modelname = f"{settings.MODEL_SETTINGS['model_name']}_epochs-{settings.MODEL_SETTINGS['train_args']['num_train_epochs']}"

# Load full dataset
dataset_fp = Path(settings.DATA_PROCESSED_DIRP) / "dataset_event_type.tsv"
dataset_df = pd.read_csv(dataset_fp, sep="\t", converters={"labels": literal_eval})

# max token seq
def tok_cnt(s):
    return len(s.split())


# Check token length 1 x 149 tokens: higher than 90 tokens are outliers and their sequence length can be truncated. 128 seq_len is more than enough
# dataset_df["token_cnt"] = dataset_df.text.map(tok_cnt)
# max_tok = sorted(dataset_df["token_cnt"].tolist(), reverse=True)
# hist = dataset_df["token_cnt"].hist(bins=20)
# plt.savefig(Path(settings.MODEL_DIRP) / "token_cnt_hist.svg")

# Train and Evaluation data needs to be in a Pandas Dataframe containing at least two columns, a 'text' and a 'labels' column. The `labels` column should contain multi-hot encoded lists.
dev_df = dataset_df[dataset_df["dataset"] == "silver"]
holdout_df = dataset_df[dataset_df["dataset"] == "gold"]

num_labels = len(dev_df["labels"][0])

# Create a MultiLabelClassificationModel
print(
    f"Cross-validating across {settings.N_FOLDS} folds with model:\n{settings.MODEL_SETTINGS}"
)

experiment_dirp = Path(settings.MODEL_DIRP) / modelname

# Collect all run metadata into a df
holdout_dirp = experiment_dirp / "holdout"
experiment_df = pd.DataFrame(
    columns=[
        "run_name",
        "result_train",
        "run_dirp",
        "train_devset_idc",
        "eval_devset_idc",
        "train_df",
        "eval_df",
    ]
)
experiment_df = experiment_df.append(
    {
        "run_name": "holdout",
        "run_dirp": str(holdout_dirp),
        "train_devset_idc": "full_devset",
        "eval_devset_idc": "full_holdout",
        "train_df": dev_df,
        "eval_df": holdout_df,
    },
    ignore_index=True,
)

# Make KFolds and collect fold splits
group_kfold = GroupKFold(n_splits=settings.N_FOLDS, )
groups = dev_df["document_id"].to_numpy()
X = dev_df["text"].to_numpy()
y = dev_df["labels"].to_numpy()

for i, (train_idc, eval_idc) in enumerate(group_kfold.split(X, y, groups)):
    print(
        f"Fold {i}: {train_idc.shape[0]} train inst. and {eval_idc.shape[0]} eval inst."
    )
    train_df = dev_df.iloc[train_idc]
    eval_df = dev_df.iloc[eval_idc]

    fold_dirp = experiment_dirp / f"fold_{i}"

    # collect run metadata
    experiment_df = experiment_df.append(
        {
            "run_name": f"fold_{i}",
            "run_dirp": str(fold_dirp),
            "train_devset_idc": train_idc,
            "eval_devset_idc": eval_idc,
            "train_df": train_df,
            "eval_df": eval_df,
        },
        ignore_index=True,
    )

# Train-eval all runs
for index, row in experiment_df.iterrows():
    run_name = row["run_name"]
    train_df = row["train_df"]
    eval_df = row["eval_df"]
    run_dirp = row["run_dirp"]
    print(
        f"{run_name.upper()}: {train_df.shape[0]} train inst. and {eval_df.shape[0]} eval inst."
    )
    result, model_outputs = train_eval(train_df, eval_df, run_dirp)

    # collect result
    print(f"{run_name.upper()}: {result}")
    row["result_train"] = result

# collect results
results_df = experiment_df[["run_name", "result_train", "run_dirp"]]

# average fold results
fold_results = results_df[results_df["run_name"].str.match("fold")][
    "result_train"
].tolist()
results_df = results_df.append(
    {
        "run_name": "all_fold_mean",
        "result_train": {
            key: np.mean([d.get(key) for d in fold_results])
            for key in reduce(operator.or_, (d.keys() for d in fold_results))
        },
    },
    ignore_index=True,
)
results_df = results_df.set_index("run_name")
print("--------------------")
print(f"Crossvalidation score: {results_df.loc['all_fold_mean', 'result_train']}")
print(f"Holdout score: {results_df.loc['holdout', 'result_train']}")

# Write experiment results
results_fp = experiment_dirp / "results.tsv"
results_df.to_csv(results_fp, sep="\t")

# write model settings
with open(experiment_dirp / "model_settings.json", "wt") as ms_out:
    json.dump(settings.MODEL_SETTINGS, ms_out)

print(
    f"Crossvalidation and holdout testing finished. All results and metadata in {experiment_dirp}"
)