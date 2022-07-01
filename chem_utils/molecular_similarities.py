"""Functions to compute the similarities between molecules."""
from itertools import product
from multiprocessing import Pool
from typing import Callable, Iterable, Optional, Union

import numpy as np
from rdkit import Chem
from rdkit.Chem.rdFMCS import FindMCS
from sklearnex import patch_sklearn
patch_sklearn()
from sklearn.metrics import pairwise_distances
from tqdm import tqdm

from chem_utils.constants import Molecule
from chem_utils.molecular_fingerprints import compute_fingerprints

SimilarityFunction = Callable[[Iterable[Molecule], Optional[Iterable[Molecule]]], np.ndarray]
SIMILARITY_FUNCTION_REGISTRY = {}


def register_similarity_function(similarity_type: str) -> Callable[[SimilarityFunction], SimilarityFunction]:
    """Creates a decorator which registers a similarity function in a global dictionary to enable access by name.

    :param similarity_type: The name to use to access the similarity function.
    :return: A decorator which will add a similarity function to the registry using the specified name.
    """
    def decorator(similarity_function: SimilarityFunction) -> SimilarityFunction:
        SIMILARITY_FUNCTION_REGISTRY[similarity_type] = similarity_function
        return similarity_function

    return decorator


def get_similarity_function(similarity_type: str) -> SimilarityFunction:
    """Gets a registered similarity function by name.

    :param similarity_type: The name of the similarity function.
    :return: The desired similarity function.
    """
    if similarity_type not in SIMILARITY_FUNCTION_REGISTRY:
        raise ValueError(f'Similarity function "{similarity_type}" could not be found.')

    return SIMILARITY_FUNCTION_REGISTRY[similarity_type]


@register_similarity_function('tanimoto')
def compute_pairwise_tanimoto_similarities(mols_1: list[Union[str, Chem.Mol]],
                                           mols_2: Optional[list[Union[str, Chem.Mol]]] = None) -> np.ndarray:
    """
    Computes pairwise Tanimoto similarities between the molecules in mols_1 and mols_2.

    :param mols_1: A list of molecules, either SMILES strings or RDKit molecules.
    :param mols_2: A list of molecules, either SMILES strings or RDKit molecules.
                   If None, copies mols_1 list.
    :return: A 2D numpy array of pairwise similarities.
    """
    # Compute Morgan fingerprints
    fps_1 = np.array(compute_fingerprints(mols_1, fingerprint_type='morgan'), dtype=bool)
    fps_2 = np.array(compute_fingerprints(mols_2, fingerprint_type='morgan'), dtype=bool) if mols_2 is not None else fps_1

    # Compute pairwise Tanimoto similarities
    tanimoto_distances = pairwise_distances(fps_1, fps_2, metric='jaccard', n_jobs=-1)
    tanimoto_similarities = 1 - tanimoto_distances

    return tanimoto_similarities


def compute_mcs_size(mols: Iterable[Chem.Mol]) -> int:
    """
    Computes the size (number of atoms) of the maximum common substructure between molecules.

    :param mols: An iterable of molecules.
    :return: The size (number of atoms) of the maximum common substructure between molecules.
    """
    return FindMCS(mols).numAtoms


@register_similarity_function('mcs')
def compute_pairwise_mcs_similarities(mols_1: list[Union[str, Chem.Mol]],
                                      mols_2: Optional[list[Union[str, Chem.Mol]]] = None) -> np.ndarray:
    """
    Computes pairwise maximum common substructure (MCS) similarities between the molecules in mols_1 and mols_2.

    :param mols_1: A list of molecules, either SMILES strings or RDKit molecules.
    :param mols_2: A list of molecules, either SMILES strings or RDKit molecules.
                   If None, copies mols_1 list.
    :return: A 2D numpy array of pairwise similarities.
    """
    # Convert SMILES to RDKit molecules if needed
    mols_1 = [Chem.MolFromSmiles(mol) if isinstance(mol, str) else mol for mol in mols_1]

    if mols_2 is not None:
        mols_2 = [Chem.MolFromSmiles(mol) if isinstance(mol, str) else mol for mol in mols_2]
    else:
        mols_2 = mols_1

    # Compute pairwise MCS similarities
    with Pool() as pool:
        pairwise_mcs = np.array(list(tqdm(pool.imap(compute_mcs_size, product(mols_1, mols_2)),
                                          total=len(mols_1) * len(mols_2))))

    pairwise_mcs = pairwise_mcs.reshape(len(mols_1), len(mols_2))

    num_atoms_2 = np.array([mol.GetNumAtoms() for mol in mols_2])
    mcs_similarities = pairwise_mcs / num_atoms_2

    return mcs_similarities


@register_similarity_function('tversky')
def compute_pairwise_tversky_similarities(mols_1: list[Union[str, Chem.Mol]],
                                          mols_2: Optional[list[Union[str, Chem.Mol]]] = None) -> np.ndarray:
    """
    Computes pairwise Tversky similarities between the molecules in mols_1 and mols_2.

    Uses alpha = 0 and beta = 1 so that the similarity is the proportion of substructures in each reference
    molecule (from mols_2) that is present in the query molecule (from mols_1).

    :param mols_1: A list of molecules, either SMILES strings or RDKit molecules.
    :param mols_2: A list of molecules, either SMILES strings or RDKit molecules.
                   If None, copies mols_1 list.
    :return: A 2D numpy array of pairwise similarities.
    """
    # Compute Morgan fingerprints
    fps_1 = np.array(compute_fingerprints(mols_1, fingerprint_type='morgan'), dtype=int)
    fps_2 = np.array(compute_fingerprints(mols_2, fingerprint_type='morgan'), dtype=int) if mols_2 is not None else fps_1

    # Compute pairwise Tversky similarities
    intersection = fps_1 @ fps_2.transpose()
    size_2 = fps_2.sum(axis=1)
    tversky_similarities = intersection / size_2

    return tversky_similarities


def compute_max_similarities(similarity_type: str,
                             mols: list[Union[str, Chem.Mol]],
                             reference_mols: Optional[list[Union[str, Chem.Mol]]] = None) -> np.ndarray:
    """Computes the maximum similarity between each molecule and a set of molecules.

    If only mols is provided, computes the maximum similarity between each molecule and every other molecule in the set.
    If reference_mols is provided, computes the maximum similarity between each molecule in mols and the molecules in
    reference_mols.

    Note: Does NOT remove duplicate SMILES before computing pairwise similarities.

    :param similarity_type: The type of similarity to compute between the molecules.
    :param mols: A list of SMILES for the molecules whose similarities should be computed.
    :param reference_mols: A list of SMILES that serves as the reference set against which similarities are computed.
    :return: The maximum similarity between each molecule and every other molecule (either in mols or reference_mols).
    """
    # Compute pairwise similarities
    pairwise_similarities = get_similarity_function(similarity_type)(mols, reference_mols)

    # Prevent comparison to self molecule
    if reference_mols is None:
        np.fill_diagonal(pairwise_similarities, -np.inf)

    # Compute maximum similarity between each molecule and the other molecules
    max_pairwise_similarities = np.max(pairwise_similarities, axis=1)

    return max_pairwise_similarities
