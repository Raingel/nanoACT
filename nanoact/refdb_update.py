#%%
from requests import get
import gzip
import os
import nanoact
import gzip
dumb = nanoact.NanoAct()
libpath = os.path.dirname(nanoact.__file__)
#%%
gbff_list = ["https://ftp.ncbi.nlm.nih.gov/refseq/TargetedLoci/Fungi/fungi.ITS.gbff.gz",
             "https://ftp.ncbi.nlm.nih.gov/refseq/TargetedLoci/Fungi/fungi.28SrRNA.gbff.gz",
             "https://ftp.ncbi.nlm.nih.gov/refseq/TargetedLoci/Fungi/fungi.18SrRNA.gbff.gz",
             "https://ftp.ncbi.nlm.nih.gov/refseq/TargetedLoci/Bacteria/bacteria.16SrRNA.gbff.gz",
             "https://ftp.ncbi.nlm.nih.gov/refseq/TargetedLoci/Bacteria/bacteria.23SrRNA.gbff.gz",
             "https://ftp.ncbi.nlm.nih.gov/refseq/TargetedLoci/Bacteria/bacteria.5SrRNA.gbff.gz",
             "https://ftp.ncbi.nlm.nih.gov/refseq/TargetedLoci/Archaea/archaea.16SrRNA.gbff.gz",
             "https://ftp.ncbi.nlm.nih.gov/refseq/TargetedLoci/Archaea/archaea.23SrRNA.gbff.gz",
             "https://ftp.ncbi.nlm.nih.gov/refseq/TargetedLoci/Archaea/archaea.5SrRNA.gbff.gz"
             ]

refdb_path = "./refdb/"


for gbff_URI in gbff_list:
    gbff_path = dumb._gbffgz_download(gbff_URI=gbff_URI, 
                          des=libpath+"/refdb/"
                          )
    dumb._gbffgz_to_taxfas(gbff_path=gbff_path,
                           des = libpath+"/refdb/"
                            )
    os.remove(gbff_path)
    
        
# %%
#Compress each taxonomic fasta file
for tax in os.listdir(refdb_path):
    if tax.endswith(".fas"):
        print("Compressing "+tax)
        with open(refdb_path+tax, "rb") as f_in:
            with gzip.open(refdb_path+tax+".gz", "wb") as f_out:
                f_out.writelines(f_in)
        os.remove(refdb_path+tax)
# %%
