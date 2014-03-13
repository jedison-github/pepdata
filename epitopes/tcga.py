# Copyright (c) 2014. Mount Sinai School of Medicine
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re

import pandas as pd
import Bio.SeqIO
from tcga_sources import TCGA_SOURCES, REFSEQ_PROTEIN_URL
from download import fetch_data

def open_maf(filename):
    """
    Load a TCGA MAF file into a Pandas DataFrame
    """
    with open(filename) as fd:
        lines_to_skip = 0
        while next(fd).startswith('#'):
            lines_to_skip += 1
    return pd.read_csv(
        filename,
        skiprows=lines_to_skip,
        sep="\t",
        low_memory=False)

def _load_maf_files(sources_dict, cancer_type = None):
    """
    Given a dictionary mapping cancer types to download urls,
    get all the source MAFs, load them as DataFrames, and then
    concatenate into a single DataFrame
    """
    data_frames = []
    if cancer_type is None:
        cancer_types = sources_dict.keys()
    elif isinstance(cancer_type, str):
        cancer_types = [cancer_type]
    else:
        assert isinstance(cancer_type, list), \
            "Cancer type must be None, str, or list but got %s" % cancer_type
        cancer_types = cancer_type

    for key in cancer_types:
        assert key in sources_dict, "Unknown cancer type %s" % key
        maf_url = sources_dict[key]
        maf_filename = key + ".maf"
        path = fetch_data(maf_filename, maf_url)
        df = open_maf(path)
        df['Cancer Type'] = key
        data_frames.append(df)
    return pd.concat(data_frames, ignore_index = True)

def load_dataframe(cancer_type = None):
    return _load_maf_files(TCGA_SOURCES, cancer_type)

def _build_refseq_id_to_protein(refseq_path):
    """
    Given the path to a local FASTA file containing
    RefSeq ID's and their protein transcripts,
    build a dictionary from IDs to transcripts
    """
    result = {}
    with open(refseq_path, 'r') as f:
        for record in Bio.SeqIO.parse(f, "fasta"):
            protein = str(record.seq)
            try:
                name = record.id.split("|")[3]
                # TODO: handle multiple entries more intelligently than this.
                if name.startswith("NP_"):
                    before_dot = name.split('.')[0]
                    result[before_dot] = protein
            except IndexError:
                pass
    return result

# patterns for how protein changes are encoded i.e. p.Q206E
SINGLE_AMINO_ACID_SUBSTITUTION = "p.([A-Z])([0-9]+)([A-Z])"
DELETION = "p.([A-Z])([0-9]+)del"

def load_mutant_peptides(
        peptide_lengths = [8,9,10,11],
        cancer_type = None):
    combined_df = load_dataframe(cancer_type = cancer_type)
    filtered = combined_df[["Refseq_prot_Id", "Protein_Change"]].dropna()
    refseq_path = fetch_data('refseq_protein.faa', REFSEQ_PROTEIN_URL)
    refseq_ids_to_protein = _build_refseq_id_to_protein(refseq_path)
    refseq_ids = filtered.Refseq_prot_Id
    subst_matches = \
        filtered.Protein_Change.str.extract(SINGLE_AMINO_ACID_SUBSTITUTION)
    # drop non-matching rows
    subst_matches = subst_matches.dropna()
    # single amino acid substitutions
    n_failed = 0
    for i, wildtype, str_position, mutation in subst_matches.itertuples():
        refseq_id = refseq_ids[i]
        protein = refseq_ids_to_protein.get(refseq_id)
        if protein is None:
            print "Couldn't find refseq ID %s" % refseq_id
            n_failed += 1
            continue
        amino_acid_pos = int(str_position) - 1
        if len(protein) <= amino_acid_pos:
            print "Protein %s too short, needed position %s but len %d" % \
                (refseq_id, str_position, len(protein))
            n_failed += 1
            continue
        old_aa = protein[amino_acid_pos]
        if old_aa != wildtype:
            print "Expected %s but got %s at position %s in %s" % \
                (wildtype, old_aa, str_position, refseq_id)
            n_failed += 1
            continue

    print "%d / %d failed" % (n_failed, len(filtered))
    return combined_df