"""Given a dataset, computes the nearest neighbor molecule by Tanimoto similarity in a second dataset."""
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd
from rdkit import Chem
from sklearnex import patch_sklearn
patch_sklearn()
from sklearn.metrics import pairwise_distances
from tap import Tap

from morgan_fingerprint import compute_morgan_fingerprints


class Args(Tap):
    data_path: Path  # Path to CSV file containing data with SMILES whose neighbors are to be computed.
    reference_data_path: Path  # Path to CSV file containing reference SMILES which will be the neighbors of data_path.
    save_path: Path  # Where the data with the neighbor info should be saved (defaults to data_path).
    smiles_column: str = 'smiles'  # Name of the column in data_path containing SMILES.
    reference_smiles_column: Optional[str] = None  # Name of the column in reference_data_path containing SMILES.
    """If None, then smiles_column is used."""
    reference_name: Optional[str] = None  # Name of the reference data when naming the new columns with neighbor info.


def compute_pairwise_tanimoto_distances(mols_1: list[Union[str, Chem.Mol]],
                                        mols_2: list[Union[str, Chem.Mol]]) -> np.ndarray:
    """
    Computes pairwise Tanimoto distances between the molecules in :attr:`mols_1` and :attr:`mols_1`.

    :param mols_1: A list of molecules, either SMILES strings or RDKit molecules.
    :param mols_2: A list of molecules, either SMILES strings or RDKit molecules.
    :return: A 2D numpy array of pairwise distances.
    """
    # Compute Morgan fingerprints
    fps_1 = np.array(compute_morgan_fingerprints(mols_1), dtype=bool)
    fps_2 = np.array(compute_morgan_fingerprints(mols_2), dtype=bool)

    # Compute pairwise distances
    tanimoto_distances = pairwise_distances(fps_1, fps_2, metric='jaccard', n_jobs=-1)

    return tanimoto_distances


def add_nearest_neighbors(data: pd.DataFrame,
                          similarities: np.ndarray,
                          reference_smiles: list[str],
                          prefix: str = '') -> None:
    """
    Adds nearest neighbors to a DataFrame.

    :param data: The Pandas DataFrame to which the nearest neighbors will be added.
    :param similarities: A NumPy matrix of Tanimoto similarities between the data SMILES (rows)
                         and the reference SMILES (columns).
    :param reference_smiles: The reference SMILES corresponding to the columns of similarities.
    :param prefix: The prefix to describe the nearest neighbors.
    """
    assert similarities.shape[1] == len(reference_smiles)

    max_similarity_indices = np.argmax(similarities, axis=1)

    data[f'{prefix}nearest_neighbor'] = [
        reference_smiles[max_similarity_index] for max_similarity_index in max_similarity_indices
    ]
    data[f'{prefix}nearest_neighbor_similarity'] = [
        similarities[i, max_similarity_index] for i, max_similarity_index in enumerate(max_similarity_indices)
    ]


def nearest_neighbor_tanimoto(data_path: Path,
                              reference_data_path: Path,
                              save_path: Path,
                              smiles_column: str = 'smiles',
                              reference_smiles_column: Optional[str] = None,
                              reference_name: Optional[str] = None):
    """Given a dataset, computes the nearest neighbor molecule by Tanimoto similarity in a second dataset.

    :param data_path: Path to CSV file containing data with SMILES whose neighbors are to be computed.
    :param reference_data_path: Path to CSV file containing reference SMILES which will be the neighbors of data_path.
    :param save_path: Where the data with the neighbor info should be saved (defaults to data_path).
    :param smiles_column: Name of the column in data_path containing SMILES.
    :param reference_smiles_column: Name of the column in reference_data_path containing SMILES.
                                    If None, then smiles_column is used.
    :param reference_name: Name of the reference data when naming the new columns with neighbor info.
    """
    # Set reference smiles column
    if reference_smiles_column is None:
        reference_smiles_column = smiles_column

    print('Loading data')
    data = pd.read_csv(data_path)
    reference_data = pd.read_csv(reference_data_path)

    # Sort reference data and drop duplicates
    reference_data.drop_duplicates(subset=reference_smiles_column, inplace=True)
    reference_data.sort_values(by=reference_smiles_column, ignore_index=True, inplace=True)

    print('Computing Morgan fingerprints')
    similarities = 1 - compute_pairwise_tanimoto_distances(
        mols_1=data[smiles_column],
        mols_2=reference_data[reference_smiles_column]
    )

    print('Finding minimum distance SMILES')
    prefix = f'{reference_name}_' if reference_name is not None else ''
    add_nearest_neighbors(
        data=data,
        similarities=similarities,
        reference_smiles=reference_data[reference_smiles_column],
        prefix=prefix
    )

    print('Saving')
    save_path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(save_path, index=False)


if __name__ == '__main__':
    nearest_neighbor_tanimoto(**Args().parse_args().as_dict())
