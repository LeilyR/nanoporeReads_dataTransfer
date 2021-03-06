#!/usr/bin/env python3
import sys
import os
import argparse
import configparser
import shutil
import pandas as pd
import subprocess as sp
from qc import *
from mapping import *
from baseCalling import base_calling

def get_parser():

    parser = argparse.ArgumentParser(description='A Pipeline to process fast5.')
    required = parser.add_argument_group('required arguments')
    optional = parser.add_argument_group('optional arguments')

    # required argumnets:
    required.add_argument("-i",
                        "--input",
                        type=str,
                        dest="input",
                        help='input path')
    required.add_argument("-r",
                        "--ref",
                        type=str,
                        dest="reference",
                        help='reference genome')
    required.add_argument("-p",
                        type=str,
                        dest="protocol",
                        help='sequencing protocol. This information is needed for mapping.'
                             'valid options are dna, rna or cdna')
    return parser

def read_flowcell_info(config):
    """
    Check the flowcell path to find the info needed for base calling
    """
    input = config["input"]["name"]
    info_dict = dict()
    base_path = os.path.join(config["paths"]["baseDir"]+input)
    if not os.path.exists(config["paths"]["outputDir"]+input):
        shutil.copytree(base_path,config["paths"]["outputDir"]+input)
    else:
        print("a flowcell with the same ID already exists!!")
    flowcell_path = os.path.join(config["paths"]["outputDir"]+input)
    info_dict["flowcell_path"] = flowcell_path
    if not os.path.exists(flowcell_path+"/fast5"):
         sys.exit("fast5 path doesnt exist.")
    info_dict["fast5"] = os.path.join(flowcell_path,"fast5")

    summary_file = [filename for filename in os.listdir(flowcell_path) if filename.startswith("final_summary")]
    if summary_file == []:
         sys.exit("final summary file doesnt exist.")
    assert len(summary_file) == 1
    summary_file = os.path.join(flowcell_path,summary_file[0])
    with open(summary_file,"r") as f:
        for line in f.readlines():
            if line.startswith("protocol="):
                info_dict["flowcell"] = line.split(":")[1]
                if info_dict["flowcell"] not in config["flowcell"]["compatible_flowcells"]:
                    sys.exit("flowcell id is not valid!")
                info_dict["kit"] = line.split(":")[2]
                if info_dict["kit"].endswith("\n"):
                    info_dict["kit"] = info_dict["kit"].split("\n")[0]
                if str(info_dict["kit"]) not in config["flowcell"]["compatible_kits"]:
                    sys.exit("kit id is not valid!")
                return info_dict

    return None

def read_samplesheet(config):
    """
        read samplesheet
    """
    sample_sheet = pd.read_csv(config["info_dict"]["flowcell_path"]+"/SampleSheet.csv",
                               sep = ",", skiprows=[0])
    print(sample_sheet)
    sample_sheet = sample_sheet.fillna("no_bc")
    assert(len(sample_sheet["barcode_kits"].unique())==1)
    bc_kit = sample_sheet["barcode_kits"].unique()[0]
    data=dict()
    for index, row in sample_sheet.iterrows():
        assert(row["Sample_ID"] not in data.keys())
        data[row["Sample_ID"]] = dict({"Sample_Name": row["Sample_Name"], "Sample_Project": row["Sample_Project"],
                                       "barcode_kits": row["barcode_kits"],"index_id": row["index_id"], "Sample_ID": row["Sample_ID"]})
    return bc_kit, data

def rename_fastq(config, data):
    fastq = os.path.join(config["info_dict"]["flowcell_path"],"fastq")
    for k, v in data.items():
        print(k, v)
        bs_fastq = fastq
        if v["barcode_kits"] is not "no_bc":
           if "BP" in v["index_id"]:
               bs = v["index_id"].split("BP")[1]
           elif "BC" in v["index_id"]:
               bs = v["index_id"].split("BC")[1]
           else:
               sys.exit("ERROR! index_id {} is not acceptable. The id should start with BP or BC! Check the sampleSheet!".format(v["index_id"]))
           bs_fastq = os.path.join(fastq,"barcode"+bs)
           v["index_id"] = "barcode"+bs
        else:
           assert(len(data)==1)
        if not os.path.exists(config["info_dict"]["flowcell_path"]+"/Project_"+v["Sample_Project"]):
           os.mkdir(config["info_dict"]["flowcell_path"]+"/Project_"+v["Sample_Project"])
        os.mkdir(config["info_dict"]["flowcell_path"]+"/Project_"+v["Sample_Project"]+"/Sample_"+v["Sample_ID"])
        sample_path = os.path.join(config["info_dict"]["flowcell_path"]+"/Project_"+v["Sample_Project"]+"/Sample_"+v["Sample_ID"])
        sample_name = v["Sample_Name"]
        cmd = "cat {}/*.fastq.gz > {}/{}.fastq.gz ;".format(bs_fastq,sample_path,sample_name)
        #cmd += "rm {}/fastq_runid*.fastq.gz".format(bs_fastq)
        sp.check_call(cmd, shell=True)
   #TODO Do we want to keep or remove all the fastq files with wrong or unknown barcodes?

def transfer_data(config, data, ref):
    """
    Trnasfer Project_ and FASTQC_Project_ to the user's directory
    """
    for k, v in data.items():
        group=v["Sample_Project"].split("_")[-1].lower()
        final_path = "/"+group+"/sequencing_data/OxfordNanopore/"+config["input"]["name"]
        if not os.path.exists(config["paths"]["groupDir"]+final_path):
            os.mkdir(config["paths"]["groupDir"]+final_path)
        final_path = os.path.join(config["paths"]["groupDir"]+final_path)

        if not os.path.exists(final_path+"/Project_"+v["Sample_Project"]):
            fastq = config["info_dict"]["flowcell_path"]+"/Project_"+v["Sample_Project"]
            shutil.copytree(fastq,final_path+"/Project_"+v["Sample_Project"])
        if not os.path.exists(final_path+"/FASTQC_Project_"+v["Sample_Project"]):
            fastqc = config["info_dict"]["flowcell_path"]+"/FASTQC_Project_"+v["Sample_Project"]
            shutil.copytree(fastqc,final_path+"/FASTQC_Project_"+v["Sample_Project"])
            analysis = final_path+"/Analysis_"+v["Sample_Project"]
            os.mkdir(analysis)
            os.mkdir(analysis+"/mapping_on_"+ref)



def report_contamination(config, data, protocol):
    if protocol == 'rna':
        mapping_rna_contamination(config, data)



def main():
    args = get_parser().parse_args()

    config = configparser.ConfigParser()
    config.read_file(open(os.path.join(os.path.dirname(__file__), 'config.ini'),'r'))

    config["input"]=dict([("name",os.path.basename(os.path.realpath(args.input)))])

    print("flowcell is found")
    info_dict = read_flowcell_info(config)
    print("data has been copied over to rapiuds")
    config["info_dict"]=info_dict

    bc_kit,data = read_samplesheet(config)
    print("base-calling starts with bc_kit "+bc_kit)
    print("data: ",data)
    base_calling(config, bc_kit)
    print("renaming fastq files starts")
    rename_fastq(config, data)
    print("QC")
    pycoQc_fastq(config,data,bc_kit)
    print("transfer data")
    transfer_data(config, data, args.reference)
    print(config["info_dict"]["kit"])
    if ("RNA" in config["info_dict"]["kit"]) or (args.protocol == 'rna') or (args.protocol == 'cdna'):
        print("minimap2 starts")
        mapping_rna(config,data, args.reference)
        pycoQc_bam(config,data, bc_kit, args.reference)
    #else:
    #    mapping_dna(config)
    print("data has been mapped")
    report_contamination(config, data, args.protocol)


if __name__== "__main__":
    main()
