"""Cached, sanitized RDKit SVG depictions."""

from __future__ import annotations

import re
from functools import lru_cache
from xml.etree import ElementTree

from rdkit import Chem, rdBase
from rdkit.Chem import Draw, rdDepictor, rdFMCS


def _changed_atoms(molecule: Chem.Mol, reference: Chem.Mol) -> tuple[int, ...]:
    result = rdFMCS.FindMCS(
        [reference, molecule],
        timeout=1,
        ringMatchesRingOnly=True,
        completeRingsOnly=True,
    )
    if result.canceled or not result.smartsString:
        return tuple(range(molecule.GetNumAtoms()))
    common = Chem.MolFromSmarts(result.smartsString)
    match = molecule.GetSubstructMatch(common) if common is not None else ()
    unchanged = set(match)
    return tuple(
        index for index in range(molecule.GetNumAtoms()) if index not in unchanged
    )


def _sanitize_svg(svg: str) -> str:
    """Strip active content and external references from generated SVG."""
    root = ElementTree.fromstring(svg)
    forbidden = {"script", "foreignObject", "iframe", "object", "embed"}
    for parent in root.iter():
        for child in list(parent):
            if child.tag.rsplit("}", 1)[-1] in forbidden:
                parent.remove(child)
        for attribute in list(parent.attrib):
            local = attribute.rsplit("}", 1)[-1].lower()
            value = parent.attrib[attribute]
            if local.startswith("on") or (
                local in {"href", "src"}
                and re.match(r"(?i)\s*(?:https?:|javascript:|data:text)", value)
            ):
                del parent.attrib[attribute]
    return ElementTree.tostring(root, encoding="unicode")


@lru_cache(maxsize=2048)
def molecule_svg(
    smiles: str,
    reference_smiles: str | None = None,
    width: int = 220,
    height: int = 150,
) -> str:
    with rdBase.BlockLogs():
        return _molecule_svg(smiles, reference_smiles, width, height)


def _molecule_svg(
    smiles: str,
    reference_smiles: str | None,
    width: int,
    height: int,
) -> str:
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise ValueError("invalid SMILES")
    rdDepictor.Compute2DCoords(molecule)
    highlighted: tuple[int, ...] = ()
    if reference_smiles:
        reference = Chem.MolFromSmiles(reference_smiles)
        if reference is not None:
            highlighted = _changed_atoms(molecule, reference)
    drawer = Draw.MolDraw2DSVG(width, height)
    options = drawer.drawOptions()
    options.clearBackground = False
    options.padding = 0.08
    options.baseFontSize = 0.56
    colors = {index: (0.88, 0.56, 0.12, 0.45) for index in highlighted}
    drawer.DrawMolecule(
        molecule,
        highlightAtoms=list(highlighted),
        highlightAtomColors=colors,
        highlightBonds=[],
    )
    drawer.FinishDrawing()
    return _sanitize_svg(drawer.GetDrawingText())
