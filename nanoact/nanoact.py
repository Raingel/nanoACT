# %%
from subprocess import Popen, PIPE, run, check_output
import gzip
import hdbscan
import numpy as np
import edlib
from matplotlib import pyplot as plt
from sklearn.manifold import MDS
import re
import shutil
from requests import get, post
import xmltodict
import pandas as pd
import json
import os
from collections import Counter
import urllib.parse
import time
from random import random
from random import sample as random_sample
import tarfile
# %%
class NanoAct():
    def __init__(self, TEMP = './temp/'):
        self.TEMP = TEMP
        try:
            os.mkdir(self.TEMP)
        except:
            pass
        if TEMP == './temp/':
            self._p(f"Temp folder is set to {self.TEMP}, you can change it by NanoAct(TEMP='your_temp_folder')")
            self._p(f"We recommend not to set the temp folder to nfs, ftp, samba, google drive, etc. as it may cause unexpected errors")
        self.fasta_ext = ['fasta','fa','fas']
        self.fastq_ext = ['fastq']
        self.lib_path = os.path.dirname(os.path.realpath(__file__))
        self.tax_id_cache = f"{self.lib_path}/taxid_cache/taxid_cache.json"
    def _lib_path(self):
        #get the path of the library
        return self.lib_path
    def _exec(self, cmd,suppress_output=True):
        if suppress_output:
            with open(os.devnull, 'w') as DEVNULL:
                out = run(cmd, stdout=DEVNULL, stderr=DEVNULL, shell=True)
            return None
        else:
            out = run(cmd, stdout=PIPE, shell=True)
            print (">>", cmd)
            print("Output:")
            print(out.stdout.decode('utf-8'))
            print("Exception:")
            print(out.stderr)
            return out.stdout.decode('utf-8'), out.stderr
    def _clean_temp(self):
        #Clean the temp folder
        try:
            shutil.rmtree(self.TEMP)
            os.mkdir(self.TEMP)
        except FileNotFoundError:
            os.mkdir(self.TEMP)
    def _exec_rt (self, cmd, prefix=""):
        p = Popen(cmd, stdout=PIPE, shell=True)
        for line in iter(p.stdout.readline, b''):
            print ('{}>>> {}'.format(prefix, line.rstrip()))
    def _IUPACde(self, seq):
        seq = str(seq)
        seq = seq.replace('R','[AG]')
        seq = seq.replace('Y','[CT]')
        seq = seq.replace('S','[GC]')
        seq = seq.replace('W','[AT]')
        seq = seq.replace('K','[GT]')
        seq = seq.replace('M','[AC]')
        seq = seq.replace('B','[CGT]')
        seq = seq.replace('D','[AGT]')
        seq = seq.replace('H','[ACT]')
        seq = seq.replace('V','[ACG]')
        seq = seq.replace('N','[ACGT]')
        return seq
    def _extract_degenerate_seq(self, seq):
        return list(self.sre_yield.AllStrings(self.IUPACde(seq.upper())))  # better
    """
    def _align_two_seq(self, seq1,seq2):
        max_score = -99
        max_alignment = None
        seq1 = self.IUPACde(str(seq1).upper())
        seq2 = self.IUPACde(str(seq2).upper())
        for s1 in self.extract_degenerate_seq(seq1):
            for s2 in self.extract_degenerate_seq(seq2):
                #Align two sequence
                aligner = Align.PairwiseAligner()
                aligner.mode = 'local'
                aligner.match_score = 1
                aligner.mismatch_score = -1
                aligner.open_gap_score = -1
                aligner.extend_gap_score = -1
                alignments = aligner.align(s1, s2)
                #Get the best alignment
                for alignment in alignments:
                    if alignment.score > max_score:
                        max_score = alignment.score
                        max_alignment = alignment
                    break
        return max_alignment,max_score
    """
    def _fastq_reader(self, handle, suppress_warning=True):
        #Custom fastq reader, which can handle the case when the quality score is inconsistent with the sequence length
        line_counter = 0
        while True:           
            line_counter += 1
            line = handle.readline()
            if not line:
                return
            if line[0] != "@":
                print("Skipped Line", line_counter, "in Fastq file does not start with '@', fastq file might be corrupted")
                continue
                #raise ValueError("Records in Fastq files should start with '@', fastq file might be corrupted")
            title = line[1:].rstrip()
            seq = handle.readline().rstrip()
            handle.readline() # skip the line starting with "+"
            qual = handle.readline().rstrip()
            if len(qual) != len(seq):
                if not suppress_warning:
                    print("Inconsistency found", title)
                #Temporary workaround (return fake qual)
                diff = len(seq) - len(qual)
                yield {"title": title, "seq": seq, "qual": qual + "#"*diff}
                pass
            else:
                yield {"title": title, "seq": seq, "qual": qual}
    def _fastq_writer(self,title,seq,qual,handle):
        handle.write("@{}\n{}\n+\n{}\n".format(title,seq,qual))
    def _fasta_reader(self, handle):
        #Custom fasta reader
        line = handle.readline()
        while True:
            if not line:
                return
            if line[0] == ">":
                title = line[1:].rstrip()
                seq = ""
                while True:
                    line = handle.readline()
                    if not line or line[0] == ">":
                        yield {"title": title, "seq": seq.replace(" ","")}
                        break
                    else:
                        seq += line.rstrip()
    def _count_seq_num (self,fastq):
        with open(fastq,'r') as count_len:
            a = count_len.readlines()    
        return len(a)/4
    def _fastq_rename_title(self, src,des): #modified seq title in fastq to number
        with open(src, "r") as f:
            with open(des, "w") as f2:
                counter = 0
                output = ""
                for line in f:
                    if line.startswith("@"):
                        output += "@seq" + str(counter) + "\n"
                        counter += 1
                    else:
                        output += line
                f2.write(output)
    def _pairwise_distance(self, s1,s2):
        #Calculate the pairwise distance between two sequences
        #This is a wrapper for edlib.align
        return edlib.align(str(s1).upper(), str(s2).upper())['editDistance']/(min(len(s1), len(s2))+0.1)*100
    def _reverse_complement(self, s):
        complement = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C', 
                      'a': 't', 't': 'a', 'c': 'g', 'g': 'c', 
                      'Y': 'R', 'R': 'Y', 'S': 'S', 'W': 'W', 
                      'y': 'r', 'r': 'y', 's': 's', 'w': 'w',
                      'K': 'M', 'M': 'K', 'B': 'V','N' : 'N',
                      'k': 'm', 'm': 'k', 'b': 'v','n' : 'n'}
        return ''.join([complement.get(base, base) for base in s[::-1]])
    def _p (self, s, end="\n"):
        print(f"[{time.strftime('%H:%M:%S', time.localtime())}] {s}", end=end)
    def _check_input_ouput(self, input_format, output_format):
        r = {}
        if input_format not in (self.fasta_ext + self.fastq_ext):
            raise ValueError(f"Input format must be one of {self.fasta_ext + self.fastq_ext}")
        if output_format not in (self.fasta_ext + self.fastq_ext + ['both']):
            raise ValueError(f"Output format must be one of {self.fasta_ext + self.fastq_ext + ['both']}")
        if input_format in self.fasta_ext and output_format in ['fastq', 'both']:
            raise ValueError("fasta file does not contain quality scores, so it cannot be converted to fastq")
        r['input'] = input_format
        r['output'] = {}
        if output_format in self.fasta_ext:
            r['output']['fasta'] = output_format
        if output_format in self.fastq_ext:
            r['output']['fastq'] = output_format
        if output_format == 'both':
            r['output']['fasta'] = 'fas'
            r['output']['fastq'] = 'fastq'
        return r
    def NCBIblast(self, seqs = ">a\nTTGTCTCCAAGATTAAGCCATGCATGTCTAAGTATAAGCAATTATACCGCGGGGGCACGAATGGCTCATTATATAAGTTATCGTTTATTTGATAGCACATTACTACATGGATAACTGTGG\n>b\nTAATACATGCTAAAAATCCCGACTTCGGAAGGGATGTATTTATTGGGTCGCTTAACGCCCTTCAGGCTTCCTGGTGATT\n"
                  ,timeout = 30):
        program = "blastn&MEGABLAST=on"
        database = "core_nt"
        encoded_queries = urllib.parse.quote(seqs)
        WORD_SIZE = 32
        EXPECT = 0.001
        # build the request
        args = "CMD=Put&PROGRAM=" + program + "&DATABASE=" + database + "&QUERY=" + encoded_queries + "&WORD_SIZE=" + str(WORD_SIZE) + "&EXPECT=" + str(EXPECT)
        url = 'https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi'
        response = post(url, data=args)
        #print("BLASTING {} sequences".format(len(seqs.split(">"))-1))
        # parse out the request id
        rid = ""
        for line in response.text.split('\n'):
            if line.startswith('    RID = '):
                rid = line.split()[2]
        #Search submitted
        self._p(f"Query {rid} submitted.")
        self._p(f"You can check the status at https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi?CMD=Get&FORMAT_OBJECT=SearchInfo&RID={rid}")
        self._p(f"And results here: https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi?CMD=Get&RID={rid}")
        # poll for results
        retry = timeout * 2
        while True:
            time.sleep(30)
            retry -= 1
            if retry == 0:
                print("Search", rid, "timed out")
                return None
            url = 'https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi?CMD=Get&FORMAT_OBJECT=SearchInfo&RID=' + rid
            response = get(url)
            if 'Status=WAITING' in response.text:
                self._p("Searching...")
                continue
            if 'Status=FAILED' in response.text:
                self._p(f"Search {rid} failed; please report to blast-help@ncbi.nlm.nih.gov.")
            if 'Status=UNKNOWN' in response.text:
                self._p(f"Search {rid} expired.")
            if 'Status=READY' in response.text:
                if 'ThereAreHits=yes' in response.text:
                    self._p("Search complete, retrieving results...")
                    break
                else:
                    self._p("No hits found.")
                    break

        # retrieve and display results
        url = f'https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi?CMD=Get&RID={rid}&FORMAT_TYPE=XML'
        self._p(f"Retrieving results from {url}")
        response = get(url)
        #Convert the XML to a dictionary
        blast_dict = xmltodict.parse(response.text)
        #Get the first hit of each query
        pool = {}

        #If there is only one query, the xml format is different
        #blast_dict['BlastOutput']['BlastOutput_iterations']['Iteration'] will be a dict instead of a list
        #So we need to convert it to a list
        if type(blast_dict['BlastOutput']['BlastOutput_iterations']['Iteration']) == dict:
            blast_dict['BlastOutput']['BlastOutput_iterations']['Iteration'] = [blast_dict['BlastOutput']['BlastOutput_iterations']['Iteration']]

        for rec in blast_dict['BlastOutput']['BlastOutput_iterations']['Iteration']:
            try:
                seq_name = rec['Iteration_query-def']
            except Exception as e:
                self._p(e)
                continue
            try: 
                hit = rec['Iteration_hits']['Hit'][0]
            except:
                hit = None
            if hit:
                acc = hit['Hit_accession']
                if type(hit['Hit_hsps']['Hsp']) == list:
                    hit_hsp = hit['Hit_hsps']['Hsp'][0]
                else:
                    hit_hsp = hit['Hit_hsps']['Hsp']
                hit_seq = hit_hsp['Hsp_hseq'].replace('-', '')
                hit_def = hit['Hit_def']
                similarity = round(int(hit_hsp['Hsp_identity'])/int(hit_hsp['Hsp_align-len']),2)
                
                pool[seq_name] = {'acc': acc, 'hit_seq': hit_seq, 'hit_def': hit_def, 'similarity': similarity, 'org': ""}
                #Get taxon info
                taxon_info_URI = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&rettype=gb&retmode=xml&id={}'.format(acc)
                try:
                    r = get(taxon_info_URI)
                    #xml to json
                    r = xmltodict.parse(r.text)
                    org = r['GBSet']['GBSeq']['GBSeq_organism']
                    #taxa = r['GBSet']['GBSeq']['GBSeq_taxonomy']
                    #Get taxid in db_xref
                    #Get db_xref
                    taxid=""
                    for i in r['GBSet']['GBSeq']['GBSeq_feature-table']['GBFeature']:
                        if i['GBFeature_key'] == 'source':
                            for j in i['GBFeature_quals']['GBQualifier']:
                                if j['GBQualifier_name'] == 'db_xref':
                                    taxid = j['GBQualifier_value'].split(':')[-1]
                    pool[seq_name].update({'org': org, 'taxid': taxid})
                except Exception as e:
                    self._p(e)
                    pass
                #Get all ranks
                ranks = {"kingdom":"incertae sedis", "phylum":"incertae sedis", "class":"incertae sedis", "order":"incertae sedis", "family":"incertae sedis", "genus":"incertae sedis"}
                try:
                    #Get details from taxid
                    if taxid == "":
                        continue
                    taxid_info_URI = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=taxonomy&rettype=xml&id={}'.format(taxid)
                    r = get(taxid_info_URI)
                    r = xmltodict.parse(r.text)
                    for i in r['TaxaSet']['Taxon']['LineageEx']['Taxon']:
                        if i['Rank'] in ranks.keys():
                            ranks[i['Rank']] = i['ScientificName']
                    pool[seq_name].update(ranks)
                except Exception as e:
                    self._p(f"Error: {taxid} {e}")
                    pass
        return pool
    def _funguild(self, org="Fusarium"):
        #Check funguild
        funguild_des = []
        guild = None
        notes = None
        try:
            funguild_des = json.loads(get(f"https://www.mycoportal.org/funguild/services/api/db_return.php?qDB=funguild_db&qField=taxon&qText={org}").text)
        except Exception as e:
            self._p(f"blast_result_pool[sample]['org'], load funguild failed {e}")
        try:
            guild = funguild_des[0]['guild']
        except:
            pass
        try:
            notes = funguild_des[0]['notes']
        except:
            pass
        return guild, notes     
    def blast_2 (self, src, des, name="blast.csv", 
                 funguild = True, 
                 startswith="con_",
                 input_format="fasta",
                 query_range=(None,None), batch = 5, timeout=30):
        #Collect all sequences
        pool_df = pd.DataFrame() 
        query_seqs=[] 
        input_ext = self._check_input_ouput(input_format, "fasta")
        for f in os.scandir(src):
            if not f.name.startswith(startswith):
                continue
            filename, ext = os.path.splitext(f.name)
            ext = ext[1:]
            if f.is_file() and ext == input_ext['input']:   
                with open(f.path, 'r') as handle:
                    if ext in self.fasta_ext:
                        seqs = list(self._fasta_reader(handle))
                    elif ext in self.fastq_ext:
                        seqs = list(self._fastq_reader(handle))
                    else:
                        continue
                    for s in seqs:
                        pool_df = pd.concat([pool_df, pd.DataFrame([s])], ignore_index=True)
                        #If sequence is too long, preserve only max_query_length in middle
                        q=s['seq'][query_range[0]:query_range[1]]
                        if len(q) == 0:
                            self._p(f"Zero query length. Check your query_range. Skipping {s['title']}")
                            continue
                        query_seqs.append(f">{s['title']}\n{q}")     
        if len(query_seqs) == 0:
            self._p("No sequence found, exiting")
            return None  
        #set title as index
        pool_df.set_index('title', inplace=True)
        for index, row in pool_df.iterrows():
            #Create fasta type seq
            pool_df.loc[index, 'fasta'] = f">{index}\n{row['seq']}\n"
            pool_df.loc[index, 'length'] = str(len(row['seq']))
            try:
                #2110_cluster_-1_r2154.fas	
                #{sample}_cluster_{cluster_no}_r{reads_count}.fas
                sample, cluster_no, reads_count = re.search("(.*)_cluster_([-0-9]+)_r(\d+)", index).groups()
                pool_df.loc[index, 'sample'] = sample
                pool_df.loc[index, 'cluster_no'] = cluster_no
                pool_df.loc[index, 'reads_count'] = reads_count
            except Exception as e:
                self._p(e)
                pass    
        #Blast all sequences
        i = 0
        blast_result_pool = {}
        while i < len(query_seqs):
            self._p(f"Blasting {i} to {i+batch} of {len(query_seqs)}")
            query = "\n".join(query_seqs[i:i+batch])
            retry = 3
            while retry >= 0:
                try:
                    blast_result = self.NCBIblast(query,timeout=timeout)
                    if blast_result != None:
                        blast_result_pool.update(blast_result)
                        break
                    else:
                        retry -= 1
                except Exception as e:
                    self._p(e)
                    retry -= 1
            i+=batch
        #print(blast_result_pool)
        for sample in blast_result_pool.keys():
            for key in blast_result_pool[sample].keys():
                pool_df.loc[sample,key] = blast_result_pool[sample][key]
            
            #Check funguild
            if funguild and blast_result_pool[sample]['org'] != "":
                guild, notes = self._funguild(blast_result_pool[sample]['org'])
                try:
                    pool_df.loc[sample,'funguild'] = guild
                except:
                    pass
                try:
                    pool_df.loc[sample,'funguild_notes'] = notes
                except:
                    pass
        pool_df.to_csv(f"{des}/{name}", encoding ='utf-8-sig')
        return f"{des}/{name}"

    def _mafft (self, src, des, adjustdirection = False):
        mafft_bin = self._lib_path() + "/bin/mafft.bat"
        #Make mafft to auto adjust direction
        #./mafft.bat --genafpair --maxiterate 1000 2110_cluster_1_r442.fas > output.fas
        if adjustdirection:
            adjustdirection = "--adjustdirection"
        else:
            adjustdirection = ""
        cmd = f"{mafft_bin} {adjustdirection} {src} > {des}"
        self._exec(cmd,suppress_output=True)
    def _gblock (self, fas):
        try:
            #try copy input file to temp folder
            shutil.copy(fas, self.TEMP)
            fas = f"{self.TEMP}/{os.path.basename(fas)}"
            self._p(f"Copy {fas} to {self.TEMP} success, running Gblocks")
        except:
            self._p(f"Copy {fas} to {self.TEMP} failed")
        gblock_bin = self._lib_path() + "/bin/Gblocks"
        #command = [bin, input_path, "-t=d", "-b5=a", f"-e={output_ext}"] # -t=d: DNA, -b5=a: 保留所有gap, -e: 輸出檔案的副檔名
        cmd = [gblock_bin, fas, "-t=d", "-b5=a", "-e=gblo"]
        cmd_line = " ".join(cmd)
        self._p(f"Running {cmd_line}")
        self._exec(cmd_line,suppress_output=True)
        output_path = f"{fas}gblo"
        #Replace space in the sequences
        seq_wo_space = ""
        with open(output_path, 'r') as handle:
            for rec in self._fasta_reader(handle):
                seq_wo_space += f">{rec['title']}\n{rec['seq'].replace(' ','')}\n"
        with open(output_path, 'w') as handle:
            handle.write(seq_wo_space)
        return output_path
    def diplod_site (self, MSA, threshold = 0.2):
        diploid_site = []
        #Check the nucleotides frequencies for each position
        from collections import Counter
        freqs = []
        for i in range(MSA.shape[1]):
            c = Counter(MSA[:,i])
            f = []
            for n in "ATCG": #"-ATCG" for gapped sequences
                ratio = c[n]/MSA.shape[0]
                f.append(ratio)
            #If the second largest frequency is larger than THRESHOLD, it is a diploid site
            if sorted(f)[-2] > threshold:
                diploid_site.append(i)
            freqs.append(f)
        freqs = np.array(freqs)
        MSA_diploid = MSA[:,diploid_site]
        return MSA_diploid, diploid_site
    def diploid_cluster (self, src, des, 
                         input_format = "fas", 
                         output_format = "fas"
                         ):
        #這個分群方法是被設計用在常規的分群(mmseqs2, hdbscan)後，若有雙型性的序列未被分出來。進行更精細的分群用的(也可能有更高的偽陽性)。他的輸入資料夾必須是經過mafft_consensus的結果，裡面必須包含aln_開頭的，已align過的檔案
        #This clustering method is designed to be used after the regular clustering (mmseqs2, hdbscan), if there are sequences with haplotypes that are not separated.
        #The input folder must be the result of mafft_consensus, which must contain the files that have been aligned and start with aln_
        io_format = self._check_input_ouput(input_format, output_format)
        try:
            os.makedirs(des, exist_ok=True)
        except:
            pass     
        #Read fasta file
        for f in os.scandir(src):
            #Get filename without extension
            if f.is_file():
                filename,ext = os.path.splitext(f.name)
                ext = ext[1:]
                if ext != io_format['input']:
                    self._p(f"{f.name} is not in the accepted input format, skipping")
                    continue
                if not f.name.startswith("aln_"):
                    self._p(f"{f.name} is not an aligned file starting with aln_, skipping")
                    continue
                self._p(f"Processing {f.name}")
                FAS = f.path
                filename = os.path.basename(FAS)
                try:
                    SampleID = filename.split("_")[1]
                    original_cluster = filename.split("_")[3]
                    original_prefix = "_".join(filename.split("_")[0:3])
                except:
                    self._p(f"Failed to parse {filename}, skipping. Make sure the filename is in the format of aln_[SampleID]_cluster_[number]_r[number].{io_format['input']}")
                #Read MSA_gblocked as 2D numpy array
                MSA_gblocked = []
                titles = []
                for rec in self._fasta_reader(open(FAS)):
                    titles.append(rec['title'])
                    MSA_gblocked.append(list(rec['seq'].upper()))
                #Convert to numpy array
                try:
                    MSA_gblocked = np.array(MSA_gblocked)
                #If inhomogeneous length, exit
                except ValueError:
                    print("Failed to read MSA. Are all sequences the same length?")
                MSA_diploid, diploid_site = self.diplod_site(MSA_gblocked, 0.2)
                #Initialize temp folder
                try:
                    shutil.rmtree(self.TEMP+"/MSA_diploid")
                except FileNotFoundError:
                    pass
                try:
                    shutil.rmtree(self.TEMP+"/MSA_gblocked_labeled")
                except FileNotFoundError:
                    pass
                try:
                    shutil.rmtree(self.TEMP+"/MSA_diploid_cluster")
                except FileNotFoundError:
                    pass
                #save MSA_diploid to temp
                os.makedirs(self.TEMP+"/MSA_diploid", exist_ok=True)
                with open(self.TEMP+"/MSA_diploid/MSA_diploid.fas", "w") as f:
                    for i in range(len(MSA_diploid)):
                        f.write(">"+titles[i]+"\n")
                        f.write("".join(MSA_diploid[i])+"\n")
                #Save MSA_gblocked to temp, diploid sites is labeled as lower case
                os.makedirs(self.TEMP+"/MSA_labeled", exist_ok=True)
                for d in diploid_site:
                    MSA_gblocked[:,d] = list("".join(MSA_gblocked[:,d]).lower())
                with open(self.TEMP+"/MSA_labeled/MSA_labeled.fas", "w") as f:
                    for i in range(len(MSA_gblocked)):
                        f.write(">"+titles[i]+"\n")
                        f.write("".join(MSA_gblocked[i])+"\n")
                self.hdbscan(self.TEMP+"/MSA_diploid",self.TEMP+"/MSA_diploid_cluster",
                input_format = "fas",
                output_format = "fas",
                min_cluster_size = 0.1, mds = False)
                #Save new clustered seq based on cluster number
                #Read original sequences
                original_seq = {}
                for rec in self._fasta_reader(open(FAS)):
                    title = rec['title']
                    seq = rec['seq']
                    original_seq[title] = seq
                for f in os.scandir(self.TEMP + "/MSA_diploid_cluster"):
                    if f.name.endswith(".fas"):
                        print(f.name)
                        #MSA_diploid_cluster_1_r650.fas
                        cluster_number = f.name.split("_")[3]
                        #Count reads in each cluster
                        reads_count = 0
                        output = ""
                        for rec in self._fasta_reader(open(f.path)):
                            title = rec['title']
                            #seq = rec['seq']
                            output += ">"+title+"\n"
                            output += original_seq[title]+"\n"
                            reads_count+=1
                        #TC_cluster_57_r1183
                        clusterID = f"{SampleID}_cluster_{original_cluster}-{cluster_number}_r{reads_count}"
                        new_aln = f"aln_{clusterID}.{io_format['output']['fasta']}"
                        new_con = f"con_{clusterID}.{io_format['output']['fasta']}"
                        with open(f"{des}/{new_aln}", "w") as fw:
                            fw.write(output)
                        self._naive_consensus(f"{des}/{new_aln}",f"{des}/{new_con}",clusterID)


    def orientation(self, src, des, 
                    input_format = "fastq",
                    output_format = "both",
                    BARCODE_INDEX_FILE = "",
                    FwPrimer = "FwPrimer",
                    RvPrimer = "RvPrimer",
                    search_range=500):
        #Input: a folder containing all the fas files, fas_file should be named as {sample_id}.fas
        #Input2: a barcode index file, containing following columns: SampleID, FwPrimer, RvPrimer
        #input_format: fastq or fasta or both
        #search_range: number of bases in the beginning of raw read to search for primer
        #Output: a folder containing sequences with the right orientation
        io_format = self._check_input_ouput(input_format, output_format)
        try:
            os.makedirs(des, exist_ok=True)
        except:
            pass
        #Read barcode index file as tsv or csv depending on the file extension
        if BARCODE_INDEX_FILE.endswith(".tsv"):
            bar_idx = pd.read_csv(BARCODE_INDEX_FILE, sep='\t')
        else:
            bar_idx = pd.read_csv(BARCODE_INDEX_FILE)
        #Read fasta file
        for f in os.scandir(src):
            #Get filename without extension
            if f.is_file():
                filename,ext = os.path.splitext(f.name)
                ext = ext[1:]
                if ext != io_format['input']:
                    self._p(f"{f.name} is not in the accepted input format, skipping")
                    continue
                self._p(f"Processing {f.name}")
                try:
                    F = bar_idx[bar_idx['SampleID'].astype(str)==filename][FwPrimer].values[0]
                    R = bar_idx[bar_idx['SampleID'].astype(str)==filename][RvPrimer].values[0]
                except IndexError:
                    self._p(f"Sample {filename} not found in the barcode file, skipping")
                    continue


                #Initialize output file
                if 'fastq' in io_format['output']:
                    output_fastq = open(f"{des}/{filename}.{io_format['output']['fastq']}", "w")
                if 'fasta' in io_format['output']:
                    output_fasta = open(f"{des}/{filename}.{io_format['output']['fasta']}", "w")
                with open(f.path) as handle:
                    with open(f"{des}/{f.name}", "w") as output:
                        if f.name.endswith(".fastq"):
                            records = self._fastq_reader(handle)
                        else:
                            f.name.endswith(".fastq")
                            records = self._fasta_reader(handle)
                        for record in records: 
                            #Check if the sequence is in the right orientation
                            aln_f = edlib.align(F.upper(), record['seq'].upper()[:search_range], mode="HW", task="locations")
                            aln_r = edlib.align(R.upper(), record['seq'].upper()[:search_range], mode="HW", task="locations")
                            if aln_f['editDistance'] > aln_r['editDistance']:
                                record['seq'] = self._reverse_complement(record['seq'])
                            #output.write(f">{record['title']}\n{record['seq']}\n")
                            if 'fasta' in io_format['output']:
                                output_fasta.write(f">{record['title']}\n{record['seq']}\n")
                            if 'fastq' in io_format['output']:
                                output_fastq.write(f"@{record['title']}\n{record['seq']}\n+\n{record['qual']}\n")
        return des
    def mafft_consensus (self, src, 
                         des, 
                         minimal_reads=0, 
                         input_format="fas",
                         #If there are too many reads, the alignment will be very slow
                         #Set max_reads to limit the number of reads to be aligned
                         #Random sampling will be performed if the number of reads exceeds max_reads
                         max_reads=10000,
                         adjustdirection = False,
                         ):
        try:
            os.makedirs(des)
        except:
            pass
        abs_des = os.path.abspath(des)
        for f in os.scandir(src):
            SampleID, ext = os.path.splitext(f.name)
            ext = ext[1:]
            input_ext = self._check_input_ouput(input_format, "fasta")
            if f.is_file():
                self._p(f"Working on {SampleID} ...")
                if ext != input_ext['input']:
                    self._p(f"{f.name} is not in the accepted input format, skipping")
                    continue
                #Check if target file exists
                if os.path.isfile(f"{abs_des}/con_{SampleID}.fas"):
                    self._p(f"{f.name} already processed, skipping")
                    continue
                if ext in self.fasta_ext:
                    #Count seq_num 
                    seq_num = len(list(self._fasta_reader(open(f.path,'r'))))
                    if seq_num < minimal_reads:
                        self._p(f"{f.name} has only {seq_num} reads, less than the {minimal_reads} reads required, skipping")
                        continue
                    fas_path = f.path
                    pass
                elif ext in self.fastq_ext:
                    #Count seq_num
                    seq_num = len(list(self._fastq_reader(open(f.path,'r'))))
                    if seq_num < minimal_reads:
                        self._p(f"{f.name} has only {seq_num} reads, less than the {minimal_reads} reads required, skipping")
                        continue
                    #Convert fastq to fasta
                    self._clean_temp()
                    fas_path = f"{self.TEMP}/from_fastq.fas"
                    self._fastq_to_fasta(f.path, fas_path)
                    pass
                else:
                    continue
                if seq_num > max_reads and max_reads > 0:
                    self._p(f"{f.name} has {seq_num} reads, more than the {max_reads} reads allowed, random sampling {max_reads} reads")
                    #Random sampling
                    with open(fas_path,'r') as handle:
                        records = list(self._fasta_reader(handle))
                        records = random_sample(records, max_reads)
                    with open(fas_path,'w') as out:
                        for rec in records:
                            out.write(f">{rec['title']}\n{rec['seq']}\n")
                #Align sequences
                self._mafft(fas_path, f"{abs_des}/aln_{SampleID}.fas", adjustdirection = adjustdirection)
                self._naive_consensus(f"{abs_des}/aln_{SampleID}.fas", f"{abs_des}/con_{SampleID}.fas", SampleID)
        return abs_des
    def _naive_consensus (self, src, des, title):
        #naive consensus
        with open(src) as handle:
            records = list(self._fasta_reader(handle))
            consensus = ""
            for i in range(len(records[0]['seq'])):
                col = [r['seq'][i] for r in records]
                #get_most_common
                com = Counter(col).most_common(1)[0][0]
                if com != "-":
                    consensus += com
            with open(des, "w") as out:
                out.write(f">{title}\n{consensus}")
    def _get_sample_id_single (self, seq, barcode_hash_table, search_range=150, mismatch_ratio_f = 0.15,mismatch_ratio_r = 0.15):
        # Define a helper function to identify the sample ID of a sequence read based on its barcode
        ids = []
        integrity = []
        seqs = []
        # Convert the input sequence read to uppercase and extract the beginning and end segments
        seq = seq.upper()
        seqF = seq[:search_range]
        seqR = seq[-search_range:]
        
        for id in barcode_hash_table:
            # Iterate through the hash table of barcodes and their corresponding index sequences
            FwIndex = barcode_hash_table[id]["FwIndex"].upper()
            RvAnchor = barcode_hash_table[id]["RvAnchor"].upper()
            # Extract the forward and reverse index sequences of the current barcode and convert to uppercase
            FwIndex_check = edlib.align(FwIndex,seqF, mode="HW", k=int(len(FwIndex) * mismatch_ratio_f), task="locations")
            RvAnchor_check = edlib.align(RvAnchor,seqR, mode="HW", k=int(len(RvAnchor) * mismatch_ratio_r), task="locations")
            # Align the forward and reverse index sequences with the beginning and end of the input sequence read, allowing for a certain number of mismatches defined by the mismatch ratio
            # print(id, FwIndex_check, FwIndex, seqF[:search_range], RvAnchor_check, RvAnchor, seqR[-search_range:])
            if FwIndex_check["editDistance"] != -1:
                #mark found region to lower case
                seqF_marked = seqF[:FwIndex_check["locations"][0][0]] + seqF[FwIndex_check["locations"][0][0]:FwIndex_check["locations"][0][1]+1].lower() + seqF[FwIndex_check["locations"][0][1]+1:]
                seqR_marked = seqR
                if RvAnchor_check["editDistance"] != -1:
                    if RvAnchor != "":
                        #If RvAnchor is set, mark found region to lower case
                        seqR_marked = seqR[:RvAnchor_check["locations"][0][0]] + seqR[RvAnchor_check["locations"][0][0]:RvAnchor_check["locations"][0][1]+1].lower() + seqR[RvAnchor_check["locations"][0][1]+1:]
                    integrity.append(True)
                else:
                    integrity.append(False)
                ids.append(id)
                seqs.append(seqF_marked +seq[search_range:-search_range] + seqR_marked)
        # If a barcode is identified, return the corresponding sample ID and a boolean indicating whether the barcode was matched with sufficient integrity
        return ids, integrity, seqs
    def singlebar(self, src, des, 
                  BARCODE_INDEX_FILE,
                    mismatch_ratio_f = 0.15,mismatch_ratio_r = 0.15, 
                    expected_length_variation = 0.3, 
                    search_range=150,
                    rvc_rvanchor = False,
                    input_format = "fastq",
                    output_format = "both",
                    ):
        """
        Input: 單個fastq檔案，例如 all.fastq
        Output: 一個資料夾，程式會在該資料夾中輸出以SampleID為檔名的fastq檔案或是fasta檔案（由output_format決定），例如 SampleID.fastq
        BARCODE_INDEX_FILE: barcode資料庫，可以是csv或是tsv檔案，例如 barcode.csv。必須包含SampleID, FwIndex, RvAnchor，ExpectedLength四個欄位。
        mismatch_ratio_f: FwIndex容許的錯誤率，預設為0.15。例如barcode長度為20bp，則容許0.15*20=3bp的錯誤(edit distance)。
        mismatch_ratio_r: RvAnchor容許的錯誤率，預設為0.15。
        expected_length_variation: 預期的read長度變異，預設為0.3。例如預期的read長度為300bp，則容許0.3*300=90bp的變異。
        search_range: 搜尋barcode的範圍，預設為150bp。代表搜尋範圍為前150bp和後150bp。
        output_format: 輸出檔案的格式，預設為both。可以是fastq或是fasta。both代表同時輸出fastq和fasta。

        1.Process the raw sequencing file using a fastq_reader function which reads in four lines at a time representing one sequencing read.
        2.For each read, call the _get_sample_id_single function to identify its corresponding sample ID and barcode integrity.
        3.If a sample ID is identified, append the read to the corresponding sample's output file.
        4.If a barcode is truncated, append it to the "TRUNCATED" dictionary.
        5.If multiple barcodes are identified, append it to the "MULTIPLE" dictionary.
        6.If no barcode is identified, append it to the "UNKNOWN" dictionary.
        7.Finally, output the demultiplexed reads into different output files based on their barcode.
        """
        io_format = self._check_input_ouput(input_format=input_format, output_format=output_format)
        # Define the main function for demultiplexing
        if BARCODE_INDEX_FILE.endswith("tsv"):
            sep = "\t"
        elif BARCODE_INDEX_FILE.endswith("csv"):
            sep = ","
        else:
            raise ValueError("BARCODE_INDEX_FILE must be a tsv or csv file")
        BARCODE_IDX_DF = pd.read_csv(BARCODE_INDEX_FILE, sep=sep)
        # Read in the barcode index file as a pandas DataFrame
        if not all([x in BARCODE_IDX_DF.columns for x in ["SampleID", "FwIndex", "RvAnchor", "ExpectedLength"]]):
            raise ValueError("BARCODE_INDEX_FILE must have SampleID, FwIndex, RvAnchor columns")
        self._p("BARCODE_INDEX_FILE loaded")
        # Check whether the barcode index file has the required columns
        barcode_hash_table = {}
        for index, row in BARCODE_IDX_DF.iterrows():
            #Check if RvAnchor is nan
            if pd.isnull(row["RvAnchor"]):
                row["RvAnchor"] = ""
            if rvc_rvanchor:
                row["RvAnchor"] = self._reverse_complement(row["RvAnchor"])
            barcode_hash_table[row["SampleID"]] = {"FwIndex": row["FwIndex"], "RvAnchor": row["RvAnchor"], "ExpectedLength": row["ExpectedLength"]}

        # Store the barcode index file as a hash table of barcode-sample ID pairs
        pool = {}
        counter = 0
        pool["UNKNOWN"] = []
        pool["MULTIPLE"] = []
        pool["TRUNCATED"] = []
        pool["IncorrectLength"] = []
        for id in barcode_hash_table:
            pool[id] = []
        # Initialize dictionaries for output files for each sample and additional dictionaries for reads with unknown, multiple, or truncated barcodes
        _, ext = os.path.splitext(src)
        ext = ext[1:]
        with open(src, "r") as handle:
            if ext in self.fastq_ext and input_format in self.fastq_ext:
                reader = self._fastq_reader(handle)
            elif ext in self.fasta_ext and input_format in self.fasta_ext:
                reader = self._fasta_reader(handle)
            else:
                raise ValueError(f"Input file extension {ext} does not match input format {input_format}")
            for record in reader:
                ids, integrity, seqs= self._get_sample_id_single(record["seq"], barcode_hash_table, search_range, mismatch_ratio_f, mismatch_ratio_r)
                if len(ids) == 1:
                    #if only one barcode is identified, append the read to the corresponding sample's output file
                    record["seq"] = seqs[0]
                    if integrity[0] == False:
                        pool["TRUNCATED"].append(record)
                    else:
                        #Check if seq in ExpectedLength
                        if (len(seqs[0]) - barcode_hash_table[ids[0]]["ExpectedLength"])**2 < (barcode_hash_table[ids[0]]["ExpectedLength"] * expected_length_variation)**2:
                            pool[ids[0]].append(record)
                        else:
                            pool["IncorrectLength"].append(record)
                elif len(ids) > 1:
                    pool["MULTIPLE"].append(record)
                else:
                    pool["UNKNOWN"].append(record)
                counter += 1

                if counter % 10000 == 0:
                    self._p(f"Parsed {counter}")
        #Save to separate fastq file
        try:
            os.makedirs(f"{des}/", exist_ok=True)
            os.makedirs(f"{des}/trash/", exist_ok=True)
        except:
            pass
        stat_df = pd.DataFrame(columns=["SampleID", "Count"])
        for bin in pool:
            stat_df = pd.concat([stat_df, pd.DataFrame({"SampleID": [bin], "Count": [len(pool[bin])]})])
            if bin in ['MULTIPLE', 'UNKNOWN', 'TRUNCATED','IncorrectLength']:
                path = f"{des}/trash/{bin}"
            else:
                path = f"{des}/{bin}"
            #Save to separate fastq or fasta file based on output_format
            #Initialize output file
            if 'fastq' in io_format['output']:
                output_fastq = open(f"{path}.{io_format['output']['fastq']}", "w")
                for record in pool[bin]:
                    output_fastq.write("@"+record["title"] + "\n")
                    output_fastq.write(record["seq"] + "\n")
                    output_fastq.write("+" + "\n")
                    output_fastq.write(record["qual"] + "\n")
            if 'fasta' in io_format['output']:
                output_fasta = open(f"{path}.{io_format['output']['fasta']}", "w")
                for record in pool[bin]:
                    output_fasta.write(">"+ record["title"] + "\n")
                    output_fasta.write(record["seq"] + "\n")

        stat_df.to_csv(f"{des}/2_Singlebar_stat.csv", index=False)
        #Print out the number of reads discarded due to unknown, multiple, or truncated barcodes
        FAILED_NUM = len(pool['UNKNOWN']) + len(pool['MULTIPLE']) + len(pool['TRUNCATED']) + len(pool['IncorrectLength'])
        self._p(f"{counter-FAILED_NUM}/{counter} ({(counter-FAILED_NUM)/counter*100:.2f}%) reads were demultiplexed successfully")
        return des

    def double_demultiplex(self, src, des, 
                        BARCODE_INDEX_FILE,
                        primers = ['FwPrimer', 'RvPrimer'],
                        mismatch_ratio_f = 0.15, mismatch_ratio_r = 0.15, 
                        expected_length_variation = 0.3, 
                        search_range = 150,
                        rvc_rvanchor = False,
                        input_format = "fastq",
                        output_format = "both",
                        ):
        """
        Input: 單個fastq檔案，例如 all.fastq
        Output: 一個資料夾，程式會在該資料夾中輸出以SampleID為檔名的fastq檔案或fasta檔案（由output_format決定），例如 SampleID.fastq
        BARCODE_INDEX_FILE: barcode資料庫，可以是csv或tsv檔案，必須包含 SampleID、FwIndex、FwPrimer、RvAnchor、RvPrimer、ExpectedLength 六個欄位。
        primers: 使用的引子（primer），預設為 ['FwPrimer', 'RvPrimer']。
        mismatch_ratio_f: FwIndex 容許的錯誤率，預設為 0.15。例如 barcode 長度為 20bp，則容許 0.15*20=3bp 的錯誤（edit distance）。
        mismatch_ratio_r: RvPrimer 容許的錯誤率，預設為 0.15。
        expected_length_variation: 預期的 read 長度變異，預設為 0.3。例如預期長度為 300bp，則容許 0.3*300=90bp 的變異。
        search_range: 搜索 barcode 的範圍，預設為 150bp。代表搜尋範圍為 read 的前 150bp 和後 150bp。
        output_format: 輸出檔案的格式，預設為 'both'。可以是 fastq 或 fasta。'both' 代表同時輸出 fastq 和 fasta。

        工作流程：
        1. 使用 `fastq_reader` 函數處理原始定序檔案，每次讀取四行代表一個定序 read。
        2. 進行兩次解多工（demultiplexing）：
        1. 第一次基於 FwIndex 將 reads 分群。
        2. 第二次基於引子（primers）進行進一步的分群。
        3. 如果識別到唯一的 Sample ID，則將 read 分配到對應 Sample 的輸出檔案中。
        4. 如果條碼被截斷，則將 read 附加到 "TRUNCATED" 字典中。
        5. 如果識別出多個條碼，則將 read 附加到 "MULTIPLE" 字典中。
        6. 如果未識別條碼，則將 read 附加到 "UNKNOWN" 字典中。
        7. 最終根據條碼將已解多工的 reads 輸出到不同檔案。
        """

        # 輸入輸出格式檢查
        io_format = self._check_input_ouput(input_format=input_format, output_format=output_format)
        
        # 載入BARCODE_INDEX_FILE檔案
        if BARCODE_INDEX_FILE.endswith("tsv"):
            sep = "\t"
        elif BARCODE_INDEX_FILE.endswith("csv"):
            sep = ","
        else:
            raise ValueError("BARCODE_INDEX_FILE 必須是 tsv 或 csv 檔案")

        BARCODE_IDX_DF = pd.read_csv(BARCODE_INDEX_FILE, sep=sep)
        
        # 檢查必要欄位
        required_columns = ["SampleID", "FwIndex", "FwPrimer", "RvAnchor", "RvPrimer", "ExpectedLength"]
        # Including user specified primers
        required_columns.extend(primers)
        if not all([col in BARCODE_IDX_DF.columns for col in required_columns]):
            raise ValueError(f"BARCODE_INDEX_FILE 必須包含這些欄位: {', '.join(required_columns)}")
        
        # 生成barcode的hash table
        barcode_hash_tables = {}
        col_used_as_barcode = ["FwIndex"] + primers
        for c in col_used_as_barcode:
            barcode_hash_tables[c] = {}
            for index, row in BARCODE_IDX_DF.iterrows():
                if rvc_rvanchor:
                    row["RvAnchor"] = self._reverse_complement(row["RvAnchor"])
                barcode_hash_tables[c][row["SampleID"]] = { 
                    "RvAnchor": row["RvAnchor"],
                    "ExpectedLength": row["ExpectedLength"],
                    }
                barcode_hash_tables[c][row["SampleID"]]["FwIndex"] = row[c]

        
        # 建立pool來儲存解多工後的reads
        pool = {id: [] for id in barcode_hash_tables["FwIndex"]}
        pool["UNKNOWN"] = []
        pool["MULTIPLE"] = []
        pool["TRUNCATED"] = []
        pool["IncorrectLength"] = []
        # 處理定序檔案
        _, ext = os.path.splitext(src)
        ext = ext[1:]
        with open(src, "r") as handle:
            if ext in self.fastq_ext and input_format in self.fastq_ext:
                reader = self._fastq_reader(handle)
            elif ext in self.fasta_ext and input_format in self.fasta_ext:
                reader = self._fasta_reader(handle)
            else:
                raise ValueError(f"Input file extension {ext} 不符合輸入格式 {input_format}")
            counter = 0
            for record in reader:
                counter += 1
                #Show current progress
                if counter % 1000 == 0:
                    self._p(f"Parsed {counter}", end="\r")
                # First pass: demultiplex based on FwIndex
                barcode_hash_table = barcode_hash_tables["FwIndex"]
                ids_from_FwIndex, integrity, seqs = self._get_sample_id_single(record["seq"], barcode_hash_table, search_range, mismatch_ratio_f, mismatch_ratio_r)
                #if no barcode is identified, append the read to the "UNKNOWN" dictionary
                if len(ids_from_FwIndex) == 0:
                    pool["UNKNOWN"].append(record)
                    continue

                # Second pass: demultiplex based on primers
                ids_from_primers = []
                for p in primers:
                    #print(f"Comparing {p}")
                    barcode_hash_table = barcode_hash_tables[p]
                    ids, _, _ = self._get_sample_id_single(record["seq"], barcode_hash_table, search_range, mismatch_ratio_f, mismatch_ratio_r)
                    ids_from_primers.extend(ids)
                # Get the intersection of ids_from_FwIndex and ids_from_primers
                ids = list(set(ids_from_FwIndex) & set(ids_from_primers))
                #print(f"Final IDs: {ids}")
                if len(ids) == 1:
                    #if only one barcode is identified, append the read to the corresponding sample's output file
                    record["seq"] = seqs[0]
                    if integrity[0] == False:
                        pool["TRUNCATED"].append(record)
                    else:
                        #Check if seq in ExpectedLength
                        if (len(seqs[0]) - barcode_hash_tables["FwIndex"][ids[0]]["ExpectedLength"])**2 < (barcode_hash_tables["FwIndex"][ids[0]]["ExpectedLength"] * expected_length_variation)**2:
                            pool[ids[0]].append(record)
                        else:
                            pool["IncorrectLength"].append(record)
                elif len(ids) > 1:
                    pool["MULTIPLE"].append(record)
                else:
                    pool["UNKNOWN"].append(record)


        #Save to separate fastq file
        try:
            os.makedirs(f"{des}/", exist_ok=True)
            os.makedirs(f"{des}/trash/", exist_ok=True)
        except:
            pass
        stat_df = pd.DataFrame(columns=["SampleID", "Count"])
        for bin in pool:
            stat_df = pd.concat([stat_df, pd.DataFrame({"SampleID": [bin], "Count": [len(pool[bin])]})])
            if bin in ['MULTIPLE', 'UNKNOWN', 'TRUNCATED','IncorrectLength']:
                path = f"{des}/trash/{bin}"
            else:
                path = f"{des}/{bin}"
            #Save to separate fastq or fasta file based on output_format
            #Initialize output file
            if 'fastq' in io_format['output']:
                output_fastq = open(f"{path}.{io_format['output']['fastq']}", "w")
                for record in pool[bin]:
                    output_fastq.write("@"+record["title"] + "\n")
                    output_fastq.write(record["seq"] + "\n")
                    output_fastq.write("+" + "\n")
                    output_fastq.write(record["qual"] + "\n")
            if 'fasta' in io_format['output']:
                output_fasta = open(f"{path}.{io_format['output']['fasta']}", "w")
                for record in pool[bin]:
                    output_fasta.write(">"+ record["title"] + "\n")
                    output_fasta.write(record["seq"] + "\n")
            
        stat_df.to_csv(f"{des}/2_Doublebar_stat.csv", index=False)
        #Print out the number of reads discarded due to unknown, multiple, or truncated barcodes
        FAILED_NUM = len(pool['UNKNOWN']) + len(pool['MULTIPLE']) + len(pool['TRUNCATED']) + len(pool['IncorrectLength'])
        self._p(f"{counter-FAILED_NUM}/{counter} ({(counter-FAILED_NUM)/counter*100:.2f}%) reads were demultiplexed successfully")
        return des
    

                    

    def _get_sample_id_dual (self, seq, barcode_hash_table, mismatch_ratio_f = 0.15, mismatch_ratio_r = 0.15):
        ids = []
        seqs = []
        # Convert the input sequence read to uppercase and extract the beginning and end segments
        seq = seq.upper()
        seqF = seq[:150]
        seqR = seq[-150:]
        seq_REV = self._reverse_complement(seq)
        seq_REV_F = seq_REV[:150]
        seq_REV_R = seq_REV[-150:]
        
        for id in barcode_hash_table:
            # Iterate through the hash table of barcodes and their corresponding index sequences
            FwIndex = barcode_hash_table[id]["FwIndex"].upper()
            RvIndex = barcode_hash_table[id]["RvIndex"].upper()
            #Reverse complement the reverse index sequence
            RvIndex = self._reverse_complement(RvIndex)
            # Extract the forward and reverse index sequences of the current barcode and convert to uppercase
            FwIndex_check = edlib.align(FwIndex,seqF, mode="HW", k=int(len(FwIndex) * mismatch_ratio_f), task="locations")
            RvIndex_check = edlib.align(RvIndex,seqR, mode="HW", k=int(len(RvIndex) * mismatch_ratio_r), task="locations")
            #Check read in reverse complement
            Fwindex_check_R = edlib.align(FwIndex,seq_REV_F, mode="HW", k=int(len(FwIndex) * mismatch_ratio_f), task="locations")
            Rvindex_check_R = edlib.align(RvIndex,seq_REV_R, mode="HW", k=int(len(RvIndex) * mismatch_ratio_r), task="locations")
            #print(FwIndex,seqF,RvIndex,seqR)
            #print("FwIndex_check",FwIndex_check, "RvIndex_check",RvIndex_check)
            if FwIndex_check["editDistance"] != -1 and RvIndex_check["editDistance"] != -1:
                #mark found region to lower case

                seqF = seqF[:FwIndex_check["locations"][0][0]] + seqF[FwIndex_check["locations"][0][0]:FwIndex_check["locations"][0][1]].lower() + seqF[FwIndex_check["locations"][0][1]:]
                seqR = seqR[:RvIndex_check["locations"][0][0]] + seqR[RvIndex_check["locations"][0][0]:RvIndex_check["locations"][0][1]].lower() + seqR[RvIndex_check["locations"][0][1]:]
                
                ids.append(id)
                seqs.append(seqF +seq[150:-150] + seqR)
            elif Fwindex_check_R["editDistance"] != -1 and Rvindex_check_R["editDistance"] != -1:
                #mark found region to lower case
                seq_REV_F = seq_REV_F[:Fwindex_check_R["locations"][0][0]] + seq_REV_F[Fwindex_check_R["locations"][0][0]:Fwindex_check_R["locations"][0][1]].lower() + seq_REV_F[Fwindex_check_R["locations"][0][1]:]
                seq_REV_R = seq_REV_R[:Rvindex_check_R["locations"][0][0]] + seq_REV_R[Rvindex_check_R["locations"][0][0]:Rvindex_check_R["locations"][0][1]].lower() + seq_REV_R[Rvindex_check_R["locations"][0][1]:]
                ids.append(id)
                seqs.append(seq_REV_F +seq[150:-150] + seq_REV_R)
        return ids, seqs
    def dualbar(self, src,des, BARCODE_INDEX_FILE, mismatch_ratio_f = 0.15,mismatch_ratio_r = 0.15, expected_length_variation = 0.3):
        """
        1.Process the raw sequencing file using a fastq_reader function which reads in four lines at a time representing one sequencing read.
        2.For each read, call the _get_sample_id_dual function to identify its corresponding sample ID and barcode integrity.
        3.If a sample ID is identified, append the read to the corresponding sample's output file.
        4.If only one barcode is identified, append it to the "SINGLE" dictionary.
        5.If multiple barcodes are identified, append it to the "MULTIPLE" dictionary.
        6.If no barcode is identified, append it to the "UNKNOWN" dictionary.
        7.Finally, output the demultiplexed reads into different output files based on their barcode.
        dumb.dualbar(
            src = "./data/1_Nanofilt/all.fastq",
            des = "./data/dualbar/",
            BARCODE_INDEX_FILE = "./data/230107_barcode.tsv",
            mismatch_ratio_f = 0.15,
            mismatch_ratio_r = 0.15, 
            expected_length_variation = 5
        )    
        """
        if BARCODE_INDEX_FILE.endswith(".tsv"):
            sep = "\t"
        elif BARCODE_INDEX_FILE.endswith(".csv"):
            sep = ","
        else:
            raise ValueError("Barcode index file must be either a .tsv or .csv file")
        BARCODE_IDX_DF = pd.read_csv(BARCODE_INDEX_FILE, sep = sep)
        #Check all columns are present
        if not all(x in BARCODE_IDX_DF.columns for x in ["SampleID","FwIndex","RvIndex", "ExpectedLength"]):
            raise ValueError("Barcode index file must contain columns: SampleID, FwIndex, RvIndex, ExpectedLength")
        print("BARCODE_INDEX_FILE loaded")
        # Create a hash table of barcodes and their corresponding index sequences
        barcode_hash_table = {}
        for index, row in BARCODE_IDX_DF.iterrows():
            barcode_hash_table[row["SampleID"]] = {"FwIndex":row["FwIndex"], "RvIndex":row["RvIndex"], "ExpectedLength": row["ExpectedLength"]}
        # Create a dictionary to store the number of reads that are demultiplexed into each sample
        pool = {}
        counter = 0
        # Create a dictionary to store the number of reads that are demultiplexed into each sample
        pool['Unknown'] = []
        pool['Multiple'] = []
        pool['IncorrectLength'] = []
        # Initialize the output files for each sample
        for id in barcode_hash_table.keys():
            pool[id] = []

        with open(src,"r") as handle:
            for record in self._fastq_reader(handle):
                #Get the sequence and quality score
                seq = record["seq"]
                #Get the barcode sequence
                ids, seqs = self._get_sample_id_dual(seq, barcode_hash_table, mismatch_ratio_f, mismatch_ratio_r)
                #Check if the barcode is identified
                if len(ids) == 1:
                    #check if seq in ExpectedLength
                    if (len(seqs[0]) - barcode_hash_table[ids[0]]["ExpectedLength"])**2 < (barcode_hash_table[ids[0]]["ExpectedLength"] * expected_length_variation)**2:
                        pool[ids[0]].append(record)
                    else:
                        pool["IncorrectLength"].append(record)
                elif len(ids) > 1:
                    pool["Multiple"].append(record)
                else:
                    pool["Unknown"].append(record)
                counter += 1
                if counter % 10000 == 0:
                    print(counter)

        #Save to separate fastq file
        try:
            os.makedirs(f"{des}/", exist_ok=True)
            os.makedirs(f"{des}/trash/", exist_ok=True)
        except:
            pass
        stat_df = pd.DataFrame(columns=["SampleID", "Count"])
        for bin in pool:
            stat_df = pd.concat([stat_df, pd.DataFrame({"SampleID": [bin], "Count": [len(pool[bin])]})])
            if bin in ['Multiple', 'Unknown','IncorrectLength']:
                path = f"{des}/trash/{bin}"
            else:
                path = f"{des}/{bin}"
            #Save to separate fastq file
            with open(path+".fastq", "w") as handle:
                for record in pool[bin]:
                    handle.write("@" + record["title"] + "\n")
                    handle.write(record["seq"] + "\n")
                    handle.write("+" + "\n")
                    handle.write(record["qual"] + "\n")
            #Save to separate fasta file
            with open(path+".fas", "w") as handle:
                for record in pool[bin]:
                    handle.write(">"+ record["title"] + "\n")
                    handle.write(record["seq"] + "\n")
        stat_df.to_csv(f"{des}/2_Dualbar_stat.csv", index=False)
        #Print out the number of reads discarded due to unknown, multiple, or truncated barcodes
        FAILED_NUM = len(pool['Unknown']) + len(pool['Multiple']) + len(pool['IncorrectLength'])
        print (f"{counter-FAILED_NUM}/{counter} ({(counter-FAILED_NUM)/counter*100:.2f}%) reads were demultiplexed successfully")
        return des  
    def combine_fastq(self, src, des, name = "all.fastq"):
        try:
            os.makedirs(des, exist_ok=True)
        except Exception as e:
            self._p(e)
            pass
        with open(f'{des}/{name}', 'w') as outfile:
            for f in os.scandir(src):
                if f.name.endswith(".fastq.gz"):
                    self._p("Found fastq file: {}".format(f.name))
                    with gzip.open(f.path, 'rt') as infile:
                        for line in infile:
                            outfile.write(line)
        return f'{des}/{name}'.format(self.TEMP)
    def nanofilt(self, src, des, name = "all.fastq", NANOFILT_QSCORE = 8,  NANOFILT_MIN_LEN = 400, NANOFILT_MAX_LEN = 8000):
        try:
            os.makedirs(des, exist_ok=True)
        except Exception as e:
            pass
        print("Start Nanoflit...")
        des += f"/{name}"
        self._exec(f"NanoFilt -q {NANOFILT_QSCORE} --length {NANOFILT_MIN_LEN} --maxlength {NANOFILT_MAX_LEN} {src} > {des}")
        raw_fastq_lines = sum(1 for line in open(src)) /4
        filtered_fastq_line = sum(1 for line in open(des)) /4
        print("Raw reads: {}, Passed: {}({}%)".format(raw_fastq_lines, filtered_fastq_line, int(filtered_fastq_line/raw_fastq_lines*100)))
        return des
    def _average_quality(self, quality_string):
        """
        Calculate the average quality score of a given quality string.

        Args:
            quality_string (str): quality string in FASTQ format.

        Returns:
            average_quality (float): the average quality score.
        """
        quality_scores = [ord(char) - 33 for char in quality_string]
        #Prevent division by zero
        if len(quality_scores) == 0:
            return 0
        average_quality = sum(quality_scores) / len(quality_scores)
        return average_quality
    def qualityfilt(self, src, des, name="all.fastq", 
                    QSCORE = 8, 
                    MIN_LEN = 400, 
                    MAX_LEN = 8000,
                    SEARCH_SEQ = [], #Search if specific DNA sequence is present in the read
                    EDIT_DISTANCE = 0, #Edit distance allowed for the search sequence, Only works if SEARCH_SEQ is not empty
                    ):
        try:
            os.makedirs(des, exist_ok=True)
        except Exception as e:
            pass
        self._p("Start Qualityfilt...")
        self._p(f"QSCORE: {QSCORE}, MIN_LEN: {MIN_LEN}, MAX_LEN: {MAX_LEN}")
        if SEARCH_SEQ:
            self._p("SEARCH_SEQ is defined, searching for specific DNA sequence")
            #Convert SEARCH_SEQ to uppercase
            SEARCH_SEQ = [s.upper() for s in SEARCH_SEQ]
        des += f"/{name}"
        total = 0
        passed = 0
        with open(src, 'r') as infile:
            with open(des, 'w') as outfile:
                for rec in self._fastq_reader(infile):
                    total += 1
                    #Search if specific DNA sequence is present in the read
                    SEARCH_FLAG = False
                    rec['seq'] = rec['seq'].upper()
                    if SEARCH_SEQ:
                        for s in SEARCH_SEQ:
                            if edlib.align(s, rec['seq'], mode="HW", task="locations")['editDistance'] <= EDIT_DISTANCE:
                                SEARCH_FLAG = True
                                break
                    else:
                        SEARCH_FLAG = True
                    #Check if the read passed the quality filter
                    if self._average_quality(rec['qual']) >= QSCORE and len(rec['seq']) >= MIN_LEN and len(rec['seq']) <= MAX_LEN and SEARCH_FLAG:
                        passed += 1
                        outfile.write(f"@{rec['title']}\n{rec['seq']}\n+\n{rec['qual']}\n")
                    print(f"{passed}/{total} ({passed/total*100:.2f}%) reads were passed quality filter", end="\r")
        self._p(f"{passed}/{total} ({passed/total*100:.2f}%) reads were passed quality filter")
        return des
    def minibar(self, src, des, BARCODE_INDEX_FILE, MINIBAR_INDEX_DIS):
        src = src
        #Check if the barcode index file is valid
        print("Checking barcode index file...")
        _, err = self._exec(f"minibar.py {BARCODE_INDEX_FILE} -info cols")
        if err:
            raise Exception("Invalid barcode index file")
        else:
            print(f"{BARCODE_INDEX_FILE} is valid")
        cwd = os.getcwd()
        os.chdir(des)
        out, err = self._exec(f"minibar.py -F -C -e {MINIBAR_INDEX_DIS} {BARCODE_INDEX_FILE} {src} 2>&1")
        os.chdir(cwd)
        return des
    def _fastq_to_fasta(self, src, des):
        #Convert a fastq file to fasta
        with open(src, 'r') as infile:
            with open(des, 'w') as outfile:
                for s in self._fastq_reader(infile, suppress_warning=True):
                    outfile.write(">{}\n{}\n".format(s['title'],s['seq']))
        return des
    def batch_to_fasta(self, src, des, ext = "fas"):
        #Convert all fastq files in a folder to fasta
        self._p("Start converting fastq to fasta...")
        for f in os.scandir(src):
            if f.name.endswith(".fastq"):
                print("Converting {}".format(f.name))
                SampleID, ext = os.path.splitext(f.name)
                self._fastq_to_fasta(f.path, f"{des}/{SampleID}.{ext}")
        return des
    def distance_matrix(self, path, TRUNCATE_HEAD_TAIL = True):
        SampleID, ext = os.path.splitext(os.path.basename(path))
        ext = ext[1:]
        with open(path, 'r') as infile:
            if ext in self.fastq_ext:
                raw = list(self._fastq_reader(infile))
            elif ext in self.fasta_ext:
                raw = list(self._fasta_reader(infile))
        if TRUNCATE_HEAD_TAIL:
            for s in raw:
                try:
                    s['seq'] = self._truncate_head_and_tail(s['seq'])
                except Exception as e:
                    1
                    #print("Labeled HEAD not found in ", s['title'])
        self._p(f"Number of records: {len(raw)}")
        #Create distance matrix
        #fill with -1
        dm = np.full((len(raw), len(raw)), 0)
        for i in range(0, len(raw)):
            for j in range(i+1, len(raw)):
                d = min(self._pairwise_distance(raw[i]["seq"], raw[j]["seq"]), self._pairwise_distance(raw[i]["seq"], self._reverse_complement(raw[j]["seq"])))
                dm[i][j] = d
                dm[j][i] = dm[i][j]
        return dm
    def _hdbscan(self, dm, min_cluster_size = 6, min_samples = 1):
        #HDBSCAN clustering
        clusterer = hdbscan.HDBSCAN(min_cluster_size = min_cluster_size, min_samples = min_samples)
        clusterer.fit(dm)
        return clusterer.labels_
    def hdbscan(self, 
                src, des, 
                input_format = "fastq",
                output_format = "both",
                min_cluster_size = 0.3, mds = True):
        io_format = self._check_input_ouput(input_format=input_format, output_format=output_format)
        try:
            os.makedirs(des, exist_ok=True)
        except Exception as e:
            self._p(e)
            pass
        abs_des = os.path.abspath(des)
        for f in os.scandir(src):
            SampleID, ext = os.path.splitext(os.path.basename(f.name))
            ext = ext[1:]
            if f.is_file() and ext == io_format['input']:
                pass
            else:
                self._p(ext, io_format['input'])
                self._p(f"{f.name} is not in the accepted input format, skipping")
                continue
            clustered_seq = {}
            self._p("Clustering {}".format(f.name))
            #Read, calculate distance matrix, cluster
            dm = self.distance_matrix(f.path)
            #cluster size is relative to the number of sequences
            #if the number of sequences is small, use absolute cluster size (2)
            abs_cluster_size = max(2,int(dm.shape[0]*min_cluster_size))
            self._p(f"abs_cluster_size: {abs_cluster_size}")
            try:
                labels = self._hdbscan(dm, abs_cluster_size) #Use relative_cluster_size
                #print(f.name, labels)
            except Exception as e:
                self._p(e)
                self._p("Clustering failed")
                continue
            #Organize sequences by cluster
            with open(f.path, 'r') as infile:
                if ext in self.fastq_ext:
                    seqs = list(self._fastq_reader(infile))
                elif ext in self.fasta_ext:
                    seqs = list(self._fasta_reader(infile))            
            for i, l in enumerate(labels):
                if l not in clustered_seq:
                    clustered_seq[l] = []
                clustered_seq[l].append(seqs[i])
            infile.close()
            self._p(f"Number of clusters: {len(clustered_seq)}")
            #Write to file
            for l in clustered_seq:
                with open(f"{abs_des}/{SampleID}_cluster_{l}_r{len(clustered_seq[l])}.fas", 'w') as outfile:
                    for s in clustered_seq[l]:
                        outfile.write(">{}\n{}\n".format(s['title'],s['seq']))
            #Visualize cluster result with mds
            if mds:
                dm_norm = dm / (dm.max()+0.01)
                mds = MDS(n_components=2,random_state=5566, dissimilarity='precomputed', normalized_stress="auto")
                mds_results = mds.fit_transform(dm_norm)
                fig, ax = plt.subplots(figsize=(15,15))
                #ax.scatter(df['PC1'], df['PC2'], c=cluster_labels, cmap='rainbow', s=18)
                ax.scatter(mds_results[:,0], mds_results[:,1], c=labels, cmap='rainbow', s=18)  
                #Save the plot
                plt.savefig(f"{des}/{f.name[:-4]}_MDS.jpg", dpi=56)
                #Do not show the plot
                plt.close()
    def lamassemble (self, src, des, mat = "/content/lamassemble/train/promethion.mat"):
        for f in os.scandir(src):
            if f.name.endswith(".fas"):
                self._exec(f'lamassemble /content/lamassemble/train/promethion.mat -a {f.path} > {des}/aln_{f.name}')
                self._exec(f'lamassemble /content/lamassemble/train/promethion.mat -c -n {f.name[:-4]} {des}/aln_{f.name} > {des}/con_{f.name}')
        return des              
    def _trim_by_case (self, src, des, fw_offset = 0, rv_offset = 0, input_format="fastq", output_format = "both"):
        #Note: this function can only be applied to fasta files generated by singlebar which labels reads as follows:
        #Head regions are labeled by minibar as HEAD(uppercase)+barcode(lowercase)+SEQ WE NEED(uppercase)+barcode(lowercase)+TAIL(uppercase)
        #Start_offset, end_offset:  adjust the position of cut off point
        #                           which is useful when  we also want to remove the primer region
        try:
            os.makedirs(des, exist_ok=True)
        except Exception as e:
            print(e)
        counter= 0
        #Check input and output format
        io_format = self._check_input_ouput(input_format, output_format)

        for f in os.scandir(src):
            SampleID, ext = os.path.splitext(os.path.basename(f.name))
            ext = ext[1:]
            if ext != io_format['input']:
                self._p(f"{f.name} is not in the accepted inpute format, skipping")
                continue
            self._p(f"Tirmming {f.name}")
            with open (f.path, 'r') as infile:
                if ext in self.fastq_ext:
                    seq_iter = self._fastq_reader(infile)
                elif ext in self.fasta_ext:
                    seq_iter = self._fasta_reader(infile)
                if "fasta" in io_format['output']:
                    outfile_fasta = open(f"{des}/{SampleID}.{io_format['output']['fasta']}", 'w')
                if "fastq" in io_format['output']:
                    outfile_fastq = open(f"{des}/{SampleID}.{io_format['output']['fastq']}", 'w')
                for s in seq_iter:
                    try:
                        #Head regions are labeled by minibar as HEAD(uppercase)+barcode(lowercase)+SEQ WE NEED(uppercase)+barcode(lowercase)+TAIL(uppercase) 
                        r = re.search("([A-Z]+)([a-z]+)([A-Z]+)([a-z]+)([A-Z]+)", s['seq'])
                        s['seq'] = s['seq'][r.start(3)+fw_offset:r.end(3)-rv_offset]
                        #If quality score is present, trim the quality score as well
                        if "qual" in s:
                            s['qual'] = s['qual'][r.start(3)+fw_offset:r.end(3)-rv_offset]
                        if output_format in  ["fasta", "both"]:
                            outfile_fasta.write(">{}\n{}\n".format(s['title'],s['seq']))
                        if output_format in  ["fastq", "both"]:
                            outfile_fastq.write("@{}\n{}\n+\n{}\n".format(s['title'],s['seq'],s['qual']))
                        counter += 1
                        #print(counter,"reads processed", end = "\r")
                    except Exception as e:
                        pass
                        #print("Labeled HEAD not found in ", s['title'])
                        
        return des
    def _trim_by_seq (self, src, des,  
                    BARCODE_INDEX_FILE,fw_col = "FwPrimer",rv_col = "RvPrimer",
                    input_format="fastq", output_format = "both",
                    fw_offset = 0, rv_offset = 0,
                    mismatch_ratio_f = 0.15,mismatch_ratio_r = 0.15,
                    discard_no_match = False,
                    check_both_directions = True,
                    reverse_complement_rv_col = True,
                    search_range = 200,
                    ):
        try:
            os.makedirs(des, exist_ok=True)
        except Exception as e:
            print(e)
        #Check input and output format
        io_format = self._check_input_ouput(input_format, output_format)
        try:
            if BARCODE_INDEX_FILE.endswith(".tsv"):
                df = pd.read_csv(BARCODE_INDEX_FILE, sep="\t")
            elif BARCODE_INDEX_FILE.endswith(".csv"):
                df = pd.read_csv(BARCODE_INDEX_FILE)
            else:
                raise Exception("BARCODE_INDEX_FILE should be a tsv or csv file")
            #Check if SampleID, FwPrimer, RvPrimer columns exist
            if not all (x in df.columns for x in ["SampleID", fw_col, rv_col]):
                raise Exception(f"BARCODE_INDEX_FILE should contain SampleID, {fw_col}, {rv_col} columns")
            #Make sure all columns are string
            df = df.astype(str)
        except Exception as e:
            print(e)


        for f in os.scandir(src):
            SampleID, ext = os.path.splitext(os.path.basename(f.name))
            ext = ext[1:]
            if f.is_file():
                if ext != io_format['input']:
                    self._p(f"{f.name} is not in the accepted input format, skipping")
                    continue
            self._p(f"Tirmming {f.name}")
            try:
                fw_trim = df.loc[df['SampleID'] == SampleID][fw_col].values[0]
                rv_trim = df.loc[df['SampleID'] == SampleID][rv_col].values[0]
                #Upper case
                fw_trim = fw_trim.upper()
                rv_trim = rv_trim.upper()
                if reverse_complement_rv_col:
                    rv_trim = self._reverse_complement(rv_trim)
            except Exception as e:
                print(e)
                print("SampleID not found in BARCODE_INDEX_FILE")
                continue
            
            with open(f.path, 'r') as infile:
                if ext in self.fastq_ext:
                    seq_iter = self._fastq_reader(infile)
                elif ext in self.fasta_ext:
                    seq_iter = self._fasta_reader(infile)
                else:
                    continue
                #Initialize output file
                if 'fastq' in io_format['output']:
                    output_fastq = open(f"{des}/{SampleID}.{io_format['output']['fastq']}", "w")
                if 'fasta' in io_format['output']:
                    output_fasta = open(f"{des}/{SampleID}.{io_format['output']['fasta']}", "w")

                #Record trimmed, no-match, and total reads
                trimmed_F = 0
                trimmed_R = 0
                total = 0
                for s in seq_iter:
                    total += 1
                    seq_upper = s['seq'].upper()
                    #Trim fw_trim from the beginning of the sequence first, then trim rv_trim from the end of the sequence
                    #And if none of fw_trim and rv_trim is found and check_both_directions is True, check the reverse complement sequence
                    #If fw_trim and rv_trim are still not found, discard the sequence if discard_no_match is True
                    fw = edlib.align(fw_trim, seq_upper[:search_range]
                                     , mode="HW", task="locations", k=int(len(fw_trim)*mismatch_ratio_f))
                    if (fw['locations'] != []):
                        trimmed_F += 1
                        s['seq'] = s['seq'][fw['locations'][0][1]+1+fw_offset:]
                        #If quality score is present, trim the quality score as well
                        if "qual" in s:
                            s['qual'] = s['qual'][fw['locations'][0][1]+1+fw_offset:]
                        seq_upper = s['seq'].upper()
                    rv = edlib.align(rv_trim, seq_upper[-search_range:]
                                     , mode="HW", task="locations", k=int(len(rv_trim)*mismatch_ratio_r))
                    if (rv['locations'] != []):
                        trimmed_R += 1
                        splice_site = len(s['seq']) - search_range + rv['locations'][0][0] - rv_offset
                        s['seq'] = s['seq'][:splice_site]
                        #If quality score is present, trim the quality score as well
                        if "qual" in s:
                            s['qual'] = s['qual'][:splice_site]
                    #If fw_trim and rv_trim are not found, check the reverse complement sequence
                    if (fw['locations'] == []) and (rv['locations'] == []) and check_both_directions:
                        s['seq'] = self._reverse_complement(s['seq'])
                        #if quality score is present, reverse it as well
                        if "qual" in s:
                            s['qual'] = s['qual'][::-1]
                        seq_upper = s['seq'].upper()
                        fw = edlib.align(fw_trim, seq_upper[:search_range]
                                         , mode="HW", task="locations", k=int(len(fw_trim)*mismatch_ratio_f))
                        if (fw['locations'] != []):
                            trimmed_F += 1
                            s['seq'] = s['seq'][fw['locations'][0][1]+1+fw_offset:]
                            #If quality score is present, trim the quality score as well
                            if "qual" in s:
                                s['qual'] = s['qual'][fw['locations'][0][1]+1+fw_offset:]
                            seq_upper = s['seq'].upper()
                        rv = edlib.align(rv_trim, seq_upper[-search_range:]
                                         , mode="HW", task="locations", k=int(len(rv_trim)*mismatch_ratio_r))
                        if (rv['locations'] != []):
                            trimmed_R += 1
                            splice_site = len(s['seq']) - search_range + rv['locations'][0][0] - rv_offset
                            s['seq'] = s['seq'][:splice_site]
                            #If quality score is present, trim the quality score as well
                            if "qual" in s:
                                s['qual'] = s['qual'][:splice_site]
                        #If fw_trim and rv_trim are still not found, discard the sequence if discard_no_match is True
                        if (fw['locations'] == []) and (rv['locations'] == []) and discard_no_match:
                            continue
                        #turn the sequence back to the original direction
                        s['seq'] = self._reverse_complement(s['seq'])
                    #If the remaining sequence is empty, discard it
                    if s['seq'] == "":
                        print(f"Discarded {s['title']} due to empty sequence after trimming")
                        continue
                    if "fasta" in io_format['output']:
                        output_fasta.write(f">{s['title']}\n{s['seq']}\n")
                    if "fastq" in io_format['output']:
                        output_fastq.write(f"@{s['title']}\n{s['seq']}\n+\n{s['qual']}\n") 
            self._p(f"{SampleID} Total reads: {total}, trimmed forward: {trimmed_F}, trimmed reverse: {trimmed_R}")
        return des
    def trim_reads(self, 
                   src, des,
                   mode="case",
                   input_format="fastq",
                    output_format="both",
                    BARCODE_INDEX_FILE = "",
                    fw_col = "FwPrimer",rv_col = "RvPrimer",
                    fw_offset = 0, rv_offset = 0,
                    mismatch_ratio_f = 0.15,mismatch_ratio_r = 0.15,
                    discard_no_match = False,
                    check_both_directions = True,
                    reverse_complement_rv_col = True,
                    search_range = 200,
                     ):
        #mode should either be "table" or "case"
        #if mode is "table", BARCODE_INDEX_FILE should be a tsv or csv file with columns SampleID, fw_col, rv_col
        #if mode is "case", BARCODE_INDEX_FILE wouldn't be used, fw_col and rv_col will also be ignored
        self._check_input_ouput(input_format, output_format)
        if mode == "table":
            self._trim_by_seq(src=src,des=des, 
                              BARCODE_INDEX_FILE=BARCODE_INDEX_FILE,
                              fw_col=fw_col, rv_col=rv_col,
                              fw_offset=fw_offset, rv_offset=rv_offset, 
                              mismatch_ratio_f=mismatch_ratio_f, mismatch_ratio_r=mismatch_ratio_r, 
                              discard_no_match=discard_no_match, 
                              check_both_directions=check_both_directions, 
                              reverse_complement_rv_col=reverse_complement_rv_col,
                               input_format=input_format,
                               output_format=output_format,
                               search_range = search_range,
                              )
        elif mode == "case":
            print("Notice: mode is set to 'case', arguments other than src, des, fw_offset, rv_offset,input_format, output_format will be ignored")
            self._trim_by_case(src=src, 
                               des=des, 
                               fw_offset=fw_offset,
                               rv_offset=rv_offset,
                               input_format=input_format, 
                               output_format=output_format)
    """
    def medaka (self, src, des, startswith="con_"):
        for f in os.scandir(src):
            if f.name.startswith(startswith) and f.name.endswith(".fas"):
                aln_file = f"{assemble}/aln_{f.name[4:]}"
                shutil.rmtree("./medaka_seq/", ignore_errors=True)
                shutil.rmtree("./medaka/", ignore_errors=True)
                os.makedirs("./medaka_seq/", exist_ok=True)
                shutil.copyfile(f.path, './medaka_seq/con_temp.fas')
                shutil.copyfile(aln_file, './medaka_seq/aln_temp.fas')
                self._exec('medaka_consensus -d "./medaka_seq/con_temp.fas" -i "./medaka_seq/aln_temp.fas" -o "./medaka" 2>&1')
                try:
                    shutil.copyfile('./medaka/consensus.fasta', f'{des}/{f.name}')
                except:
                    pass
    """
    def blast(self, src, des, name="blast.csv", funguild = True, startswith="con_"):
        pool = []
        for f in os.scandir(src):
            row = {}
            if f.name.startswith(startswith) and f.name.endswith(".fas"):
                print("Blasting", f.name)
                with open(f.path, 'r') as handle:
                    raw = list(self._fasta_reader(handle))
                    for s in raw:
                        row['name'] = s['title']
                        row['seq'] = s['seq']
                        row['length'] = len(s['seq'])
                        try:
                            #con_sample_B11TUSc50_rDNA_cluster_1_r6
                            info = s['title'].split('cluster')[1]
                            row['cluster'] = info.split("_")[1]
                            row['reads'] = info.split("_")[2].replace("r","")
                        except:
                            pass
                try:
                    blast = self._blast(row['seq'])
                    row['organism'] = blast['org']
                    row['taxa'] = blast['taxa']
                    row['BLAST_simil'] = blast['sim']
                    row['BLAST_acc'] = blast['acc']
                    row['BLAST_seq'] = blast['seq']
                except:
                    pass

                #return {'acc':acc, 'org':org, 'taxa':taxo, 'sim':sim, 'seq':seq}
                #Check funguild
                if funguild:
                    funguild_des = []
                    try:
                        funguild_des = json.loads(get(f"https://www.mycoportal.org/funguild/services/api/db_return.php?qDB=funguild_db&qField=taxon&qText={row['organism']}").text)
                    except:
                        pass
                    if funguild_des != []:
                        #print(funguild_des)
                        try:
                            row['funguild'] = funguild_des[0]['guild']
                        except:
                            pass
                        try:
                            row['funguild_notes'] = funguild_des[0]['notes']
                        except:
                            pass
                print(row)
                pool.append(row)
        
        #pd.DataFrame(pool)[['name','cluster','reads', 'organism','taxa','seq', 'BLAST_simil','BLAST_acc','BLAST_seq', 'funguild', 'funguild_notes']].to_csv(f"{des}/blast.csv", index=False)
        pd.DataFrame(pool).to_csv(f"{des}/{name}", index=False)
        return f"{des}/{name}"
    def mmseqs_cluster(self, 
                       src, des, 
                       mmseqs="mmseqs",  #Use mmseqs or mmseqs_sse41. if are in VirtualBox or very old CPU which does not support AVX2, use mmseqs_sse41
                       input_format = "fastq",
                       output_format = "both",
                       min_seq_id=0.5, cov_mode=0, k=14, 
                       threads=8, s=7.5, 
                       cluster_mode=0, 
                       min_read_num = 0,
                       min_read_ratio = 0,
                       kmer_per_seq = 20,
                       suppress_output=True,
                       tmp = "",
                       dbtype = "2"):
        #If tmp for mmseqs is on NFS or other cloud storage, it will cause some unknown issues in mmseqs. So let user specify a local tmp folder if needed.
        if tmp == "":
            tmp = f"{self.TEMP}/tmp"

        if cluster_mode not in [0,1,2,'linclust']:
            raise ValueError("cluster_mode must be one of 0,1,2,'linclust'")
        #Get current library file  path
        lib = os.path.dirname(os.path.realpath(__file__))
        #bin should be mmseqs or mmseqs_sse41, depending on the CPU
        if mmseqs not in ["mmseqs", "mmseqs_sse41"]:
            raise ValueError("mmseqs must be one of 'mmseqs', 'mmseqs_sse41'")
        mmseqs = f"{lib}/bin/{mmseqs}"
        io_format = self._check_input_ouput(input_format=input_format, output_format=output_format)
        try:
            os.makedirs(des)
        except:
            pass
        abs_des = os.path.abspath(des)
        for f in os.scandir(src):
            SampleID, ext = os.path.splitext(os.path.basename(f.name))
            ext = ext[1:]
            if f.is_file() and ext == io_format['input']:
                pass
            else:
                self._p(f"{f.name} is not in the accepted input format, skipping")
                continue
            #clean up temp folder
            self._clean_temp()
            #Convert fastq to fasta before clustering
            if ext in self.fasta_ext:
                fas_path = f.path
            else:
                fas_path = f"{self.TEMP}/from_fastq.fas"
                self._fastq_to_fasta(f.path, fas_path)
            self._p(f"Clustering {f.name}")

            #build db
            #print("Creating db")
            self._exec(f"{mmseqs} createdb {fas_path} {self.TEMP}/db --dbtype {dbtype}", suppress_output=suppress_output)
            #cluster
            #print("Clustering")
            if  cluster_mode == 'linclust':
                self._exec(f"{mmseqs} linclust {self.TEMP}/db {self.TEMP}/cluster {tmp} --kmer-per-seq {kmer_per_seq} --min-seq-id {min_seq_id} --cov-mode {cov_mode} --threads {threads}", suppress_output=suppress_output)
            else:
                self._exec(f"{mmseqs} cluster {self.TEMP}/db {self.TEMP}/cluster {tmp} --min-seq-id {min_seq_id} --cov-mode {cov_mode} -k {k} --threads {threads} -s {s} --cluster-mode {cluster_mode}", suppress_output=suppress_output)
            #export tsv

            #self._exec(f"{mmseqs} createtsv {self.TEMP}/db {self.TEMP}/db {self.TEMP}/cluster {self.TEMP}/cluster.tsv")
            #export fasta
            #print("Parsing result")
            self._exec(f"{mmseqs} createseqfiledb {self.TEMP}/db {self.TEMP}/cluster {self.TEMP}/cluster.seq", suppress_output=suppress_output)
            self._exec(f"{mmseqs} result2flat {self.TEMP}/db {self.TEMP}/db {self.TEMP}/cluster.seq {self.TEMP}/cluster.fas", suppress_output=suppress_output)
            try:
                with open(f"{self.TEMP}/cluster.fas", 'r') as handle:
                    #Read original sequences
                    with open(f.path, 'r') as rawfile:
                        if ext in self.fasta_ext:
                            raw_reads = list(self._fasta_reader(rawfile))
                            raw_reads = {r['title']:{'title':r['title'], 'seq':r['seq']} for r in raw_reads}
                        elif ext in self.fastq_ext:
                            raw_reads = list(self._fastq_reader(rawfile))
                            raw_reads = {r['title']:{'title':r['title'], 'seq':r['seq'], 'qual':r['qual']} for r in raw_reads}
                        else:
                            raise ValueError("Invalid input format")
                        #Save raw_reads number for calculating read ratio
                        raw_reads_num = len(raw_reads)
                    bin = {}
                    cluster_no = -1
                    for rec in self._fasta_reader(handle):
                        if rec['seq'] == "":
                            cluster_no +=1
                            bin[cluster_no] = []
                            continue
                        else:
                            #append use raw_reads, because only raw_reads may contain quality score
                            bin[cluster_no].append(raw_reads[rec['title']])
            except Exception as e:
                self._p(f"Error reading output file, {e}")
                continue
            #save each cluster to file
            self._p(f"Number of clusters {len(bin)}")
            for cluster_no in bin:
                if len(bin[cluster_no]) < int(max(min_read_num, min_read_ratio*raw_reads_num)):
                    continue
                if 'fasta' in io_format['output']:
                    with open(f"{abs_des}/{SampleID}_cluster_{cluster_no}_r{len(bin[cluster_no])}.fas", 'w') as handle:
                        for rec in bin[cluster_no]:
                            handle.write(f">{rec['title']}\n{rec['seq']}\n")
                if 'fastq' in io_format['output']:
                    with open(f"{abs_des}/{SampleID}_cluster_{cluster_no}_r{len(bin[cluster_no])}.fastq", 'w') as handle:
                        for rec in bin[cluster_no]:
                            handle.write(f"@{rec['title']}\n{rec['seq']}\n+\n{rec['qual']}\n")
        return des
    def vsearch_OTUs(self, src, des, 
                     input_format = "fastq",
                     output_format = "both",
                     vsearch="/nanoact/bin/vsearch", 
                     id=0.9,
                     suppress_output=True):
        #Get current library file  path
        lib = os.path.dirname(os.path.realpath(__file__))
        vsearch = f"{lib}/bin/vsearch"
        io_format = self._check_input_ouput(input_format=input_format, output_format=output_format)
        try:
            os.makedirs(des)
        except:
            pass
        abs_des = os.path.abspath(des)
        for f in os.scandir(src):
            SampleID, ext = os.path.splitext(os.path.basename(f.name))
            ext = ext[1:]
            if f.is_file() and ext == io_format['input']:
                pass
            else:
                self._p(f"{f.name} is not in the accepted input format, skipping")
                continue
            print("Clustering", f.name)   
            #clean up temp folder
            self._clean_temp()
            #Convert fastq to fasta before clustering
            if ext in self.fasta_ext:
                fas_path = f.path
            else:
                fas_path = f"{self.TEMP}/from_fastq.fas"
                self._fastq_to_fasta(f.path, fas_path)
            self._exec(f"{vsearch} --cluster_size {fas_path} --id {id} --strand plus --sizein --sizeout --fasta_width 0 --uc {self.TEMP}/all.clustered.uc --relabel OTU_ --centroids {self.TEMP}/all.otus.fasta --otutabout {self.TEMP}/all.otutab.txt --clusters {self.TEMP}/cluster ",
                        suppress_output=suppress_output
                        )
            #read cluster uc file
            try:
                uc = pd.read_csv(f"{self.TEMP}/all.clustered.uc", sep="\t", header=None)
            except:
                print("Error reading output file", SampleID)
                continue
            #Writing each cluster to file
            uc = uc[uc[0].isin(["S","H"])]
            uc.sort_values(by=8,ascending=False,inplace=True)
            if input_format == "fastq":
                seqs = list(self._fastq_reader(open(f.path,"r")))
            else:
                seqs = list(self._fasta_reader(open(f.path,"r")))
            seqs = sorted(seqs,key=lambda d: d['title'])
            #export row 8 and row 1 as a list with {key:8 and value:1}
            seq_name_clust = uc[[8,1]].to_dict(orient="records")
            #separate each cluster to bin
            bin = {}
            for name_clust in seq_name_clust:
                for seq in seqs:
                    if name_clust[8] in seq['title']:
                        try:
                            bin[name_clust[1]].append(seq)
                        except KeyError:
                            bin[name_clust[1]] = [seq]
                        #remove seq from seqs to speed up next search
                        seqs.remove(seq)
                        break
            for cluster_no in bin:
                if 'fasta' in io_format['output']:
                    with open(f"{abs_des}/{SampleID}_cluster_{cluster_no}_r{len(bin[cluster_no])}.fas", 'w') as handle:
                        for seq in bin[cluster_no]:
                            handle.write(f">{seq['title']}\n{seq['seq']}\n")
                if 'fastq' in io_format['output']:
                    with open(f"{abs_des}/{SampleID}_cluster_{cluster_no}_r{len(bin[cluster_no])}.fastq", 'w') as handle:
                        for seq in bin[cluster_no]:
                            handle.write(f"@{seq['title']}\n{seq['seq']}\n+\n{seq['qual']}\n")
            #Copy otu table to destination
            shutil.copy(f"{self.TEMP}/all.otutab.txt", f"{abs_des}/{SampleID}_otu_table.txt")
            shutil.copy(f"{self.TEMP}/all.otus.fasta", f"{abs_des}/{SampleID}.centroid")
            shutil.copy(f"{self.TEMP}/all.clustered.uc", f"{abs_des}/{SampleID}.uc")
    def cd_hit_est(self, src, des, 
                   input_format = "fastq",
                   output_format = "both",                   
                   cd_hit_est="./nanoact/bin/cd-hit-est", 
                   id=0.8, n=5,suppress_output=True):
        #Get current library file  path
        lib = os.path.dirname(os.path.realpath(__file__))
        cd_hit_est = f"{lib}/bin/cd-hit-est"
        self._check_input_ouput(input_format=input_format, output_format=output_format)
        try:
            os.makedirs(des)
        except:
            pass
        abs_des = os.path.abspath(des)
        for f in os.scandir(src):
            SampleID, ext = os.path.splitext(os.path.basename(f.name))
            if f.is_file() and ext in self.fasta_ext and input_format == "fasta":
                pass
            elif f.is_file() and ext in self.fastq_ext and input_format == "fastq":
                pass
            else:
                continue
            print("Clustering", f.name)   
    
            #clean up temp folder
            self._clean_temp()

            #Convert fastq to fasta before clustering
            if ext in self.fasta_ext:
                fas_path = f.path
            else:
                fas_path = f"{self.TEMP}/from_fastq.fas"
                self._fastq_to_fasta(f.path, fas_path)
            #-i input file
            #-o output file
            #-c sequence identity threshold
            #-n Suggested word size: 8,9,10 for thresholds 0.90 ~ 1.0 7 for thresholds 0.88 ~ 0.9 6 for thresholds 0.85 ~ 0.88 5 for thresholds 0.80 ~ 0.85 4 for thresholds 0.75 ~ 0.8
            #-d length of description in .clstr file, default 20
            self._exec(f"{cd_hit_est} -i {fas_path} -o {self.TEMP}/cdhit.fas -c {id} -n {n} -d 0",suppress_output=suppress_output)
            #Try read clstr file
            try:
                with open(f"{self.TEMP}/cdhit.fas.clstr", 'r') as handle:
                    bin = {}
                    for line in handle:
                        if line.startswith(">Cluster"):
                            cluster_no = line.split()[1]
                            bin[cluster_no] = []
                        else:
                            title = line.split(">")[1].split("...")[0]
                            bin[cluster_no].append(title)
            except:
                print("Error reading output file", SampleID)
                continue

            #Reading original sequence file
            if input_format == "fastq":
                seqs = list(self._fastq_reader(open(f.path,"r")))
            else:
                seqs = list(self._fasta_reader(open(f.path,"r")))
            #Write each cluster to a file
            for cluster in bin:
                if output_format in ['both','fastq']:
                    fastq_handle = open(f"{abs_des}/{SampleID}_cluster_{cluster}_r{len(bin[cluster])}.fastq", 'w')
                if output_format in ['both','fasta']:
                    fasta_handle = open(f"{abs_des}/{SampleID}_cluster_{cluster}_r{len(bin[cluster])}.fas", 'w')
                with open(f"{abs_des}/{SampleID}_cluster_{cluster}_r{len(bin[cluster])}.fas", 'w') as handle:
                    for seq_title in bin[cluster]:
                        for read in seqs:
                            if seq_title in read['title']:
                                if output_format in ['both','fastq']:
                                    fastq_handle.write(f"@{read['title']}\n{read['seq']}\n+\n{read['qual']}\n")
                                if output_format in ['both','fasta']:
                                    fasta_handle.write(f">{read['title']}\n{read['seq']}\n")
                                #remove used read from the list, so that it won't be used again
                                seqs.remove(read)
                                break
    def _calculate_5mer_frequency(self, sequence):
        frequency = {}
        for i in range(len(sequence) - 4):
            kmer = sequence[i:i+5]
            frequency[kmer] = frequency.get(kmer, 0) + 1
        return frequency
    def fas_to_5mer(self, fas_path):
        frequency_vectors = []
        sequences = []
        for rec in self._fasta_reader(open(fas_path,"r")):
            frequency_vectors.append(self._calculate_5mer_frequency(rec['seq']))
            sequences.append(rec['title'])
        # Create a DataFrame to store the frequency vectors
        df = pd.DataFrame(frequency_vectors)
        # Add a column for the sequence identifiers
        df['Sequence'] = ['Sequence {}'.format(i+1) for i in range(len(sequences))]
        # Reorder the columns to have 'Sequence' as the first column
        df = df[['Sequence'] + list(df.columns[:-1])]
        #fill nan with 0
        df.fillna(0, inplace=True)
        return df
    def random_sampler(self, src, des, input_format='fastq', output_format='both', ratio=0.2):
        io_format = self._check_input_ouput(input_format, output_format)
        with open(src, 'r') as handle:
            SampleID, ext = os.path.splitext(os.path.basename(src))
            ext = ext[1:]
            if ext in self.fasta_ext:
                seqs = self._fasta_reader(handle)
            elif ext in self.fastq_ext:
                seqs = self._fastq_reader(handle)
            if 'fastq' in io_format['output']:
                fastq_handle = open(f"{des}/{SampleID}_{ratio}.{io_format['output']['fastq']}", 'w')
            if 'fasta' in io_format['output']:
                fasta_handle = open(f"{des}/{SampleID}_{ratio}.{io_format['output']['fasta']}", 'w')
            total = 0
            sampled = 0
            for seq in seqs:
                if random() < ratio:
                    if 'fasta' in io_format['output']:
                        fasta_handle.write(f">{seq['title']}\n{seq['seq']}\n")
                    if 'fastq' in io_format['output']:
                        fastq_handle.write(f"@{seq['title']}\n{seq['seq']}\n+\n{seq['qual']}\n")
                    sampled += 1
                total += 1
            self._p(f"Total reads: {total}, sampled reads: {sampled}, ratio: {sampled/total}")
    def region_extract (self, src, des, input_format='fastq', output_format='both', 
                        #Demo for ITS region of fungi
                        splicer={"start":("TCATTTAGAG","GCCCGTCGCT","GAAGTAAAAG","TCGTAACAAG"),
                                 "end":("GCTGAACTTA","GCATATCAA","ATCAATAAGCG","AAGCGGAGGA")
                                 },

                        k=1,
                            
                        ):
        io_format = self._check_input_ouput(input_format=input_format, output_format=output_format)
        try:
            os.mkdir(des)
        except:
            pass
        for f in os.scandir(src):     
            SampleID, ext = os.path.splitext(f.name)
            ext = ext[1:]
            if ext != io_format['input']:
                self._p(f"{f.name} is not in the accepted input format, skipping")
                continue
            if input_format == 'fasta' and ext in  self.fasta_ext:
                seqs = self._fasta_reader(open(f.path,"r"))
            elif input_format == 'fastq' and ext in self.fastq_ext:
                seqs = self._fastq_reader(open(f.path,"r"))
            else:
                continue
            print("Processing file: ", f.name)

            if 'fastq' in io_format['output']:
                output_fastq = open(f"{des}/{SampleID}.{io_format['output']['fastq']}", "w")
            if 'fasta' in io_format['output']:
                output_fasta = open(f"{des}/{SampleID}.{io_format['output']['fasta']}", "w")

            total_reads = 0
            total_extracted = 0
            for seq in seqs:
                total_reads += 1
                start = -1
                end = -1
                for splice in splicer['start']:
                    aln = edlib.align(splice, seq['seq'], mode="HW", task="locations", k=k)
                    if aln['locations'] != []:
                        start = aln['locations'][0][0]
                        break
                for splice in splicer['end']:
                    aln = edlib.align(splice, seq['seq'], mode="HW", task="locations", k=k)
                    if aln['locations'] != []:
                        end = aln['locations'][0][1]+1
                        break
                #if both start and end are found
                if start != -1 and end != -1 and len(seq['seq'][start:end]) > 0:
                    #Save the extracted region
                    if 'fasta' in io_format['output']:
                        output_fasta.write(f">{seq['title']}\n{seq['seq'][start:end]}\n")
                    if 'fastq' in io_format['output']:
                        output_fastq.write(f"@{seq['title']}\n{seq['seq'][start:end]}\n+\n{seq['qual'][start:end]}\n")
                    total_extracted += 1
            self._p(f"{SampleID} Total reads: {total_reads}, extracted reads: {total_extracted}, ratio: {total_extracted/total_reads}")

    def _get_gbff_by_acc(self, 
        accession_no = ['LC729284','LC729293']
        ):
        URI = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id={}&rettype=gbwithparts&retmode=text'.format(",".join(accession_no))
        data = get(URI)
        return data.text   
    def _gbff_reader(self, handle):
        line = handle.readline()
        data = {}
        while line:
            if line.startswith("ACCESSION"):
                data["accession"] = line.split()[1]
            if line.startswith("  ORGANISM  "):
                data["organism"] = line.replace("  ORGANISM  ", "").strip()
            if line.startswith('                     /db_xref="taxon:'):
                data["taxid"] = line.replace('                     /db_xref="taxon:', "").replace('"', "").strip()

            if line.startswith("ORIGIN"):
                line = handle.readline()
                seq = ""
                while not line.startswith("//"):
                    seq += line.replace(" ", "").replace("\n", "").replace("\r", "").replace("0", "").replace("1", "").replace("2", "").replace("3", "").replace("4", "").replace("5", "").replace("6", "").replace("7", "").replace("8", "").replace("9", "").upper()
                    line = handle.readline()
                data["seq"] = seq
            
            if line.startswith("//"):
                yield data
                data = {}    
            line = handle.readline()
    def _lineage_by_taxid(self, taxid=['3016022', '2888342']):
        #try load tax_id_cache from cache file
        ranks = {} 
        try:
            taxid_json = json.load(open(self.tax_id_cache, 'r'))
        except:
            taxid_json = {}
        #Add requested taxid to ranks if it is in cache
        #And remove it from taxid list
        new_taxid = []
        for t in taxid:
            if t in taxid_json:
                ranks[t] = taxid_json[t]
            else:
                new_taxid.append(t)
        #If all taxid are in cache, return ranks
        if len(new_taxid) == 0:
            return ranks
        
        # Get taxon info by taxid
        taxid_info_URI = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=taxonomy&rettype=xml&id={}'.format(",".join(new_taxid))
        r = get(taxid_info_URI)
        try:
            r = xmltodict.parse(r.text)
        except:
            print(taxid_info_URI)
            print(r.text)
            return None
        rank_base = {"kingdom":"incertae sedis", "phylum":"incertae sedis", "class":"incertae sedis", "order":"incertae sedis", "family":"incertae sedis", "genus":"incertae sedis"}
        try:
            
            #If there is only one taxid, the result will be a dict
            if isinstance(r["TaxaSet"]["Taxon"], dict):
                r["TaxaSet"]["Taxon"] = [r["TaxaSet"]["Taxon"]]
            for query in r["TaxaSet"]["Taxon"]:
                
                rank = rank_base.copy()
                #Get taxon of this taxid. Because the taxon of this taxid is not included in the LineageEx
                tid_name = query['ScientificName']
                tid_rank = query['Rank']
                if tid_rank == 'superkingdom':
                    tid_rank = 'kingdom'
                if tid_rank in rank.keys():
                    rank[tid_rank] = tid_name
                #If there is only one lineage, the result will be a dict
                if isinstance(query['LineageEx']['Taxon'], dict):
                    query['LineageEx']['Taxon'] = [query['LineageEx']['Taxon']]
                for i in query['LineageEx']['Taxon']:
                    if i['Rank'] == 'superkingdom':
                        #For Bacteria and Archaea
                        i['Rank'] = 'kingdom'
                    if i['Rank'] in rank.keys():
                        rank[i['Rank']] = i['ScientificName']
                ranks[query['TaxId']] = rank
                #Save taxid info to cache
                taxid_json[query['TaxId']] = rank
                
        except Exception as e:
            print(taxid_info_URI)
            print(r, e)
            pass
        #Save taxid info to cache
        json.dump(taxid_json, open(self.tax_id_cache, 'w'))
        return ranks
    
    def _gbffgz_download(self,gbff_URI, des):
       
        #URI = "https://ftp.ncbi.nlm.nih.gov/refseq/TargetedLoci/Fungi/fungi.ITS.gbff.gz"
        name = gbff_URI.split("/")[-1]
        basename, _ = os.path.splitext(name)
        self._p(f"Downloading {name} database from NCBI refseq ftp...")
        r = get(gbff_URI, allow_redirects=True)
        open(f"{des}/{name}", 'wb').write(r.content)
        if name.endswith(".gz"):
            #Extract gbff.gz
            self._p("Extracting gbff.gz file...")
            with gzip.open(f"{des}/{name}", 'rb') as f_in:
                with open(f"{des}/{basename}", 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            #Delete gbff.gz
            os.remove(f"{des}/{name}")
            return f"{des}/{basename}"
        else:
            return f"{des}/{name}"
    def _gbffgz_to_taxfas(self, gbff_path, des):
        name = gbff_path.split("/")[-1]
        name, _ = os.path.splitext(name)
        recs = list(self._gbff_reader(open(gbff_path, 'r')))
        #Get taxinfo for each record
        self._p("Getting taxinfo for each record...")
        taxinfos = {}
        taxid_list = set()
        for rec in recs:
            taxid_list.add(rec["taxid"])
        #Retrieve taxon info by taxid, 100 taxids per request
        batch = 100
        for i in range(0, len(taxid_list), batch):
            taxinfos.update(self._lineage_by_taxid(list(taxid_list)[i:i+batch]))
            self._p(f"{len(taxinfos)}/{len(taxid_list)} taxid processed...", end="\r")
        self._p(f"{len(taxinfos)}/{len(taxid_list)} taxid processed...")
        #write fasta
        with open(f"{des}/{name}.fas", 'w') as f:
            for rec in recs:
                try:
                    lineage = ";".join([taxinfos[rec["taxid"]][i] for i in ["kingdom", "phylum", "class", "order", "family", "genus"]])
                except Exception as e:
                    lineage = ";".join(["Unclassified"]*6)
                title = "{}||{}||{}||{}".format(rec["accession"], rec["organism"], lineage, rec["taxid"])
                title = title.replace(" ", "_")
                f.write(">{}\n{}\n".format(title, rec["seq"]))  
        return f"{des}/{name}.fas"     
    def _prepare_ref_db(self, 
                        des = "",
                        custom_acc=[],
                        custom_gbff=[],
                        ref_db = ['fungi.ITS','bacteria.16SrRNA'],
                        ):
        if des == "":
            des = f"{self.TEMP}/ref_db.fas"
        self._clean_temp()
        custom_fas = []
        #Download custom_db
        if custom_acc != []:
            self._p("Downloading custom database from NCBI...")
            cus_des = f"{self.TEMP}/custom_db.gbff"
            gbff = ""
            #Download 100 acc at a time
            for i in range(0, len(custom_acc), 100):
                gbff += self._get_gbff_by_acc(custom_acc[i:i+100])
            with open(cus_des, 'w') as f:
                f.write(gbff)
            fas = self._gbffgz_to_taxfas(cus_des, self.TEMP)
            custom_fas.append(fas)
        #Download custom_gbff
        if custom_gbff != []:
            self._p("Downloading custom gbff file from NCBI...")
            for gbff_URI in custom_gbff:
                gbff_path = self._gbffgz_download(gbff_URI, self.TEMP)
                fas = self._gbffgz_to_taxfas(gbff_path, self.TEMP)
                custom_fas.append(fas)
        #Merge custom_fas and fas.gz in refdb folder into {self.TEMP}/ref_db.fas
        self._p("Merging custom database and ref_db...")
        with open(des, 'w') as handle:
            #Load ref_db from https://github.com/Raingel/nanoact_refdb/raw/master/refdb/
            for r in ref_db:
                try:
                    self._p(f"Downloading ref_db: {r}")
                    r_URI = f"https://github.com/Raingel/nanoact_refdb/raw/master/refdb/{r}.fas.gz"
                    #Check if file exists
                    r_path = f"{self.TEMP}/{r}.fas.gz"
                    if not os.path.isfile(r_path):
                        r = get(r_URI, allow_redirects=True)
                        open(r_path, 'wb').write(r.content)
                    #Write content of r to handle
                    with gzip.open(r_path, 'rb') as f_in:
                        handle.write(f_in.read().decode("utf-8"))
                except Exception as e:
                    self._p(f"Error: {r}.fas.gz load failed.")
            #Load custom_db
            for f in custom_fas:
                with open(f, 'r') as f:
                    handle.write(f.read())
        self._p(f"ref_db prepared at: {des}")
        return des
    def local_blast (self,
                     src,
                     des,
                     name = "blast.csv",
                     startswith="con_",
                     input_format = 'fastq',
                     ref_db = ['fungi.ITS','bacteria.16SrRNA'],
                     #custom_acc = ['LC729284', 'LC729293', 'LC729281', 'LC729294', 'LC729290', 'LC729267', 'LC729273'],
                     custom_acc = [],
                    custom_gbff = [],
                    suppress_mmseqs_output = True,
                     ):
        
        des = os.path.abspath(des)
        #clean temp folder
        self._clean_temp()
        try:
            os.mkdir(des)
        except:
            pass
        #Prepare ref_db
        ref_db = self._prepare_ref_db( 
                        des = "",
                        custom_acc=custom_acc,
                        custom_gbff=custom_gbff,
                        ref_db = ref_db,
                        )
        #Merge all seq from src into one file
        self._p("Preparing query file...")
        query = f"{self.TEMP}/query.fas"
        query_handle = open(query, 'w')
        file_count = 0
        rec_count = 0
        query_tmp = {}
        for f in os.scandir(src):
            SampleID, ext = os.path.splitext(f.name)
            ext = ext[1:]
            if ext == input_format and f.name.startswith(startswith):
                with open(f.path) as handle:
                    if ext in self.fastq_ext:
                        recs = self._fastq_reader(handle)
                    elif ext in self.fasta_ext:
                        recs = self._fasta_reader(handle)
                    else:
                        raise Exception("Input format not supported")
                    for rec in recs:
                        query_handle.write(">{}\n{}\n".format(rec["title"], rec["seq"]))
                        query_tmp[rec["title"]] = rec["seq"]
                        rec_count += 1
                file_count += 1
        query_handle.close()
        self._p(f"Query file prepared. {rec_count} reads from {file_count} files.")
        #If no reads in query file, return
        if rec_count == 0:
            self._p("No reads in query file. Process terminated.")
            return
        #Binary path
        mmseqs = f"{self.lib_path}/bin/mmseqs"
        self._p("Running mmseqs easy-search...")
        self._exec(f"{mmseqs}  easy-search {query} {ref_db} {self.TEMP}/result.m8 {self.TEMP}/tmp --search-type 3", suppress_output=suppress_mmseqs_output)
        #Post process result.m8
        self._p("Post processing result.m8...")
        try:
            res_m8 = pd.read_csv(f"{self.TEMP}/result.m8", sep="\t", header=None)
            res_m8.columns = ["qseqid", "sseqid", "pident", "length", "mismatch", "gapopen", "qstart", "qend", "sstart", "send", "evalue", "bitscore"]
            res_m8 = res_m8.sort_values(by=["qseqid", "bitscore"], ascending=[True, False])
            res_m8 = res_m8.drop_duplicates(subset=["qseqid"], keep="first")
        except:
            self._p("Post processing failed. Please turn off suppress_mmseqs_output and check mmseqs output.")
            return des
        
        #Reorganize result.m8
        #title	seq	length	sample	cluster_no	reads_count	acc	hit_seq	hit_def	similarity	org	taxid	kingdom	phylum	class	order	family	genus	funguild	funguild_notes
        new_res_m8 = pd.DataFrame()
        for index, row in res_m8.iterrows():
            new_res_m8.loc[index, 'title'] = row['qseqid']
            new_res_m8.loc[index, 'seq'] = query_tmp[row['qseqid']]
            new_res_m8.loc[index, 'fasta'] = f">{row['qseqid']}\n{query_tmp[row['qseqid']]}\n"
            new_res_m8.loc[index, 'length'] = len(query_tmp[row['qseqid']])
            try:
                #T10_cluster_0_r7
                sample, cluster_no, read_no = re.search("(.*)_cluster_([-0-9]+)_r(\d+)", row['qseqid']).groups()
                new_res_m8.loc[index, 'sample'] = sample
                new_res_m8.loc[index, 'cluster_no'] = cluster_no
                read_no = read_no.replace("r", "")
                read_no = read_no.split(".")[0]
                new_res_m8.loc[index, 'reads_count'] = read_no
            except Exception as e:
                #self._p(f"Error: {row['sseqid']} split failed.")
                new_res_m8.loc[index, 'sample'] = ""
                new_res_m8.loc[index, 'cluster_no'] = ""
                new_res_m8.loc[index, 'reads_count'] = ""
            try:
                #>NR_175125||Lasionectria_atrorubra||Fungi;Ascomycota;Sordariomycetes;Hypocreales;Nectriaceae;Lasionectria||2082544
                acc, hit_def, lineage, taxid = row['sseqid'].split("||")
                kingdom, phylum, class_, order, family, genus = lineage.split(";")
            except:
                acc, hit_def, lineage, taxid = "", "", "", ""
                kingdom, phylum, class_, order, family, genus = "", "", "", "", "", ""
            new_res_m8.loc[index, 'acc'] = acc
            new_res_m8.loc[index, 'hit_def'] = hit_def
            new_res_m8.loc[index, 'similarity'] = row['pident']
            new_res_m8.loc[index, 'org'] = hit_def
            new_res_m8.loc[index, 'taxid'] = taxid
            new_res_m8.loc[index, 'kingdom'] = kingdom
            new_res_m8.loc[index, 'phylum'] = phylum
            new_res_m8.loc[index, 'class'] = class_
            new_res_m8.loc[index, 'order'] = order
            new_res_m8.loc[index, 'family'] = family
            new_res_m8.loc[index, 'genus'] = genus
            guild, notes = self._funguild(hit_def) 
            new_res_m8.loc[index, 'funguild'] = guild
            new_res_m8.loc[index, 'funguild_notes'] = notes
        #remove index
        new_res_m8.to_csv(f"{des}/{name}", index=False)
        return f"{des}/{name}"




    def taxonomy_assign(self, src, des, 
                        input_format='fastq',
                        lca_mode = 3, 
                        #custom_acc = ['LC729284', 'LC729293', 'LC729281', 'LC729294', 'LC729290', 'LC729267', 'LC729273'],
                        custom_acc = [],
                        custom_gbff = [],
                        ref_db = ['fungi.ITS','bacteria.16SrRNA'],
                        sensitivity = 7.5,
                        suppress_mmseqs_output=True,
        ):
        """
        Available ref_db:
        archaea.16SrRNA
        archaea.23SrRNA
        archaea.5SrRNA
        bacteria.16SrRNA
        bacteria.23SrRNA
        bacteria.5SrRNA
        fungi.18SrRNA
        fungi.28SrRNA
        fungi.ITS
        plant_rbcl
        """
        des = os.path.abspath(des)
        mode = "lca" #Another mode, easy-search is deprecated
        #Clean temp folder
        self._clean_temp()
        custom_fas = []
        try:
            os.mkdir(des)
        except:
            pass
        #Prepare ref_db
        ref_db = self._prepare_ref_db( 
                        des = "",
                        custom_acc=custom_acc,
                        custom_gbff=custom_gbff,
                        ref_db = ref_db,
                        )

        #Binary path
        mmseqs = f"{self.lib_path}/bin/mmseqs"

        #if mode == 'lca', taxdump and ref_db must be prepared
        if mode == 'lca':
            #build db
            self._p("Building ref_db from ref_db.fas...")
            self._exec(f'{mmseqs} createdb {ref_db} {self.TEMP}/ref_db', suppress_output=suppress_mmseqs_output)
            #Edit lookup table to include taxonomic information
            with open(f"{self.TEMP}/ref_db.lookup", "r") as f:
                lines = f.readlines()
            #Overwrite lookup table
            with open(f"{self.TEMP}/ref_db.taxidmapping", "w") as f:
                for line in lines:
                    ele = line.split('	')
                    tax_id = ele[1].split('||')[-1]
                    #Delete first element
                    ele[2] = tax_id
                    del ele[0]
                    f.write('	'.join(ele)+"\n")  
            #Download taxdump which contains taxonomic information from NCBI
            taxdump_URI = "https://ftp.ncbi.nih.gov/pub/taxonomy/taxdump.tar.gz"
            try:
                os.makedirs(f"{self.TEMP}/ncbi-taxdump")
            except Exception as e:
                pass
            self._p("Downloading taxdump from NCBI...")
            with open(f"{self.TEMP}/ncbi-taxdump/taxdump.tar.gz", "wb") as f:
                response = get(taxdump_URI)
                f.write(response.content)
            #Extract taxdump
            with tarfile.open(f"{self.TEMP}/ncbi-taxdump/taxdump.tar.gz", "r:gz") as tar:
                tar.extractall(path=f"{self.TEMP}/ncbi-taxdump")
            #Create taxonomic database with createtaxdb
            self._exec(f"{mmseqs} createtaxdb {self.TEMP}/ref_db {self.TEMP}/tmp --ncbi-tax-dump {self.TEMP}/ncbi-taxdump/ --tax-mapping-file {self.TEMP}/ref_db.taxidmapping",
                        suppress_output=suppress_mmseqs_output)

        #Start taxonomy assignment
        input_ext = self._check_input_ouput(input_format, "fasta")
        for f in os.scandir(src):
            SampleID, ext = os.path.splitext(f.name)
            ext = ext[1:]
            if ext == input_ext['input']:
                if ext in self.fasta_ext:
                    seqs = self._fasta_reader(open(f.path,"r"))
                elif ext in self.fastq_ext:
                    seqs = self._fastq_reader(open(f.path,"r"))
            else:
                continue
            self._p(f"Processing file: {f.name}")
            #Prepare query and db file
            query = f"{self.TEMP}/query.fas"
            with open(query, 'w') as f:
                for seq in seqs:
                    f.write(">{}\n{}\n".format(seq["title"], seq["seq"]))
            #DEPRECATED: mmseqs easy-search 
            if  mode == 'lca':
                #Create query db
                self._exec(f"{mmseqs} createdb {query} {self.TEMP}/{SampleID}_query_db", suppress_output=suppress_mmseqs_output)
                #Run lca
                self._exec(f"{mmseqs} taxonomy {self.TEMP}/{SampleID}_query_db {self.TEMP}/ref_db {des}/{SampleID}_taxonomyResult {self.TEMP}/tmp --search-type 3 --lca-mode {lca_mode} -s {sensitivity}", suppress_output=suppress_mmseqs_output)
                #Parse lca result to tsv
                self._exec(f"{mmseqs} createtsv {self.TEMP}/{SampleID}_query_db  {des}/{SampleID}_taxonomyResult {des}/{SampleID}_taxonomyResult.tsv", suppress_output=suppress_mmseqs_output)
                #Parse tsv file to produce report
                self._exec(f"{mmseqs} taxonomyreport {self.TEMP}/ref_db {des}/{SampleID}_taxonomyResult {des}/{SampleID}_taxonomyResultReport", suppress_output=suppress_mmseqs_output)
                self._exec(f"{mmseqs} taxonomyreport {self.TEMP}/ref_db {des}/{SampleID}_taxonomyResult {des}/{SampleID}_taxonomyResultReport.html --report-mode 1", suppress_output=suppress_mmseqs_output)

    def custom_taxonomy_sankey(self, src, des, img_ext = "png", minimal_reads=1,vertical_scale=1):  
        from sankeyflow import Sankey
        for f in os.scandir(src):
            if f.name.endswith("_taxonomyResult.tsv"):
                result_tsv = f.path
                SampleID, _ = os.path.splitext(f.name)
            else:
                continue
            print("Processing file: ", f.name)
            result_df_raw = pd.read_csv(result_tsv, sep="\t", header=None)
            #Group by second column and count
            result_df = result_df_raw.groupby(result_df_raw.columns[1]).count()
            #Flatten df
            result_df = result_df.reset_index()
            #Remove where taxid = 0 which means unclassified
            if 0 in result_df[1].tolist():
                unclassified_count = result_df[result_df[1] == 0][0].sum()
            else:
                unclassified_count = 0
            result_df = result_df[result_df[1] != 0]
            #Get tax_id rank pair from result_df_raw
            tax_id_rank = result_df_raw[[1,2]].drop_duplicates()
            #Convert to dict
            tax_id_rank = tax_id_rank.set_index(1).to_dict()[2]
            #Get tax_id list as string
            tax_id = result_df[1].astype(str).tolist()
            tax_id_count = result_df[0].tolist()
            #Get lineage of each taxid, 100 query per request
            tax_id_lineage = {}
            for i in range(0, len(tax_id), 100):
                tax_id_lineage.update(self._lineage_by_taxid(tax_id[i:i+100]))
            RANK = ["kingdom","phylum","class","order","family","genus"]
            RANK_COLOR = [(255/255, 183/255, 178/255, 0.5), 
                (205/255, 220/255, 57/255, 0.5), 
                (100/255, 181/255, 246/255, 0.5), 
                (255/255, 241/255, 118/255, 0.5), 
                (255/255, 138/255, 101/255, 0.5), 
                (171/255, 71/255, 188/255, 0.5)]
            #Add lineage on result_df_raw
            result_df_raw[RANK] = result_df_raw[1].astype(str).apply(lambda x: pd.Series(tax_id_lineage.get(x, {r: "" for r in RANK})))
            #Add frequency column for each rank
            for r in RANK:
                result_df_raw[r+"_freq"] = result_df_raw[r].map(result_df_raw[r].value_counts())
            #Sort by freq of each rank
            result_df_raw = result_df_raw.sort_values(by=[r+"_freq" for r in RANK], ascending=False)
            flow_st = []
            flow_count = []
            node_label = []
            node_count = []
            for index, row in result_df_raw.iterrows():
                identified_rank = row[2]
                for r_no, r in enumerate(RANK):
                    if r_no + 1 == len(RANK):
                        break
                    #If identified rank reached, stop
                    if r == identified_rank:
                        break
                    src_rank = RANK[r_no]
                    tar_rank = RANK[r_no+1]
                    #If empty, skip
                    if row[tar_rank] == "":
                        continue
                    src = f"{src_rank}_{row[src_rank]}"
                    tar = f"{tar_rank}_{row[tar_rank]}"
                    #build flow
                    st = (src, tar)
                    if st not in flow_st:
                        flow_st.append(st)
                        flow_count.append(1)
                    else:
                        flow_count[flow_st.index(st)] += 1
                    #build node
                    if src not in node_label:
                        node_label.append(src)
                        node_count.append(1)
                    else:
                        node_count[node_label.index(src)] += 1
                    #for last rank, they will not be as source
                    if r_no + 2 == len(RANK) or tar_rank == identified_rank:
                        if tar not in node_label:
                            node_label.append(tar)
                            node_count.append(1)
                        else:
                            node_count[node_label.index(tar)] += 1
            #Build Sankey format
            sankey_flow = [(st[0],st[1],c,
                            {"color": RANK_COLOR[RANK.index(st[0].split("_")[0])]})
                        for st,c in zip(flow_st,flow_count) 
                        ]
            sankey_node = [[] for _ in RANK]
            for n, c in zip(node_label, node_count):
                r = n.split("_")[0]
                r_no = RANK.index(r)
                sankey_node[r_no].append((n,c,{"color": "grey"}))
            #Remove count < minimal_reads
            sankey_flow = [f for f in sankey_flow if f[2] >= minimal_reads]
            sankey_node = [[n for n in r if n[1] >= minimal_reads] for r in sankey_node]
            #return sankey_flow
            genus_count = len(sankey_node[-1])
            fig,ax = plt.subplots(figsize=(30,0.8*genus_count*vertical_scale))
            s = Sankey(flows=sankey_flow, 
            nodes=sankey_node,
            flow_color_mode='source',
            node_opts=dict(
                            label_format='{label} ({value:.0f})',
                            label_opts=dict(fontsize=16),
                            label_pos='right',
                            ),
            label_pad_x = 10,
            scale=0.1)
            s.draw(ax=ax)
            ax.axis("off")
            #Save to file
            fig.savefig(f"{des}/{SampleID}.{img_ext}", bbox_inches='tight')
        return {des}
    #Deprecated
    def _taxonomy_assign_visualizer(self, src, des, minimal_reads=1,vertical_scale=0.8):
        from sankeyflow import Sankey
        for f in os.scandir(src):
            if f.name.endswith("_taxonomyassignment.csv"):
                tax_assign = pd.read_csv(f.path)
            else:
                continue
            SampleID = f.name.replace("_taxonomyassignment.csv","")
            print("Processing file: ", f.name)
            #Initialize some variables
            RANK = ["kingdom","phylum","class","order","family","genus"]
            RANK_COLOR = [(255/255, 183/255, 178/255, 0.5), 
                        (205/255, 220/255, 57/255, 0.5), 
                        (100/255, 181/255, 246/255, 0.5), 
                        (255/255, 241/255, 118/255, 0.5), 
                        (255/255, 138/255, 101/255, 0.5), 
                        (171/255, 71/255, 188/255, 0.5)]
            # Add frequency for each rank
            for r in RANK:
                tax_assign[f"{r}_freq"] = tax_assign[r].map(tax_assign[r].value_counts())
            #Discard freq <=1
            for r in RANK:
                tax_assign = tax_assign[tax_assign[f"{r}_freq"]>=minimal_reads]
            #Sort by the frequency of each rank
            tax_assign = tax_assign.sort_values(by=[f"{RANK[0]}_freq",f"{RANK[1]}_freq",f"{RANK[2]}_freq",f"{RANK[3]}_freq",f"{RANK[4]}_freq",f"{RANK[5]}_freq"], ascending=False)
            #Building source_target_occurrence data
            src_tar = {}
            tax_list = []
            tax_occurence = {}
            for index, row in tax_assign.iterrows():
                #extract rank to rank pair id
                for r_no, r1 in enumerate(RANK):
                    #Get the next rank, if the rank is the last rank, set it to None
                    r2 = RANK[r_no+1] if r_no+1 < len(RANK) else None
                    #Get the id of r1 rank in the row
                    try:
                        #See if the rank is already in the list
                        id1 = tax_list.index(f"{r1}_{row[r1]}")
                    except:
                        #If the rank is first time to appear, add it to the list
                        tax_list.append(f"{r1}_{row[r1]}")
                        id1 = tax_list.index(f"{r1}_{row[r1]}")

                    #Count the occurence of the rank
                    tax_occurence[f"{r1}_{row[r1]}"] = tax_occurence.get(f"{r1}_{row[r1]}",0) + 1
                    if r2 == None:
                        continue
                    #Get the id of r2 rank in the row
                    try:
                        #See if the rank is already in the list
                        id2 = tax_list.index(f"{r2}_{row[r2]}")
                    except:
                        #If the rank is first time to appear, add it to the list
                        tax_list.append(f"{r2}_{row[r2]}")
                        id2 = tax_list.index(f"{r2}_{row[r2]}")

                    src_tar[(id1,id2)] = src_tar.get((id1,id2),0) + 1
                    """ 
                    Example:
                    (0, 1): 607,
                    (1, 2): 606,
                    (2, 3): 606,
                    (3, 4): 606,
                    (4, 5): 606,
                    """

            #Building input data for Sankey
            nodes_name = {key:[] for key in RANK}
            nodes_num = {key:[] for key in RANK}
            flows = []
            #Save a copy df of the src_tar
            src_tar_df = pd.DataFrame()
            for s_t in src_tar:
                MINIMUM_READS = 1
                if src_tar[s_t] < MINIMUM_READS:
                    continue
                s = tax_list[s_t[0]]
                t = tax_list[s_t[1]]
                r_s, taxon = s.split("_")[0], "_".join(s.split("_")[1:])
                r_s_id = RANK.index(r_s)
                color = RANK_COLOR[r_s_id]
                flows.append([s,t,src_tar[s_t],{'color':color}])
                #Save info to src_tar_df
                src_tar_df = pd.concat([src_tar_df,
                                        pd.DataFrame([[s,t,s_t[0],s_t[1],src_tar[s_t],r_s,color]],
                                                    columns=["source","target","source_id","target_id","value","source_rank", "color_by_rank"])]
                                        )   
                #Save info for nodes
                if taxon not in nodes_name[r_s]:
                    nodes_name[r_s].append(taxon)
                    nodes_num[r_s].append(src_tar[s_t])
                else:
                    nodes_num[r_s][nodes_name[r_s].index(taxon)] += src_tar[s_t]
                #Genus will not appear in the s, so we need to add it manually
                t_s, taxon = t.split("_")[0], "_".join(t.split("_")[1:])
                if t_s == "genus":
                    if taxon not in nodes_name[t_s]:
                        nodes_name[t_s].append(taxon)
                        nodes_num[t_s].append(src_tar[s_t])
                    else:
                        nodes_num[t_s][nodes_name[t_s].index(taxon)] += src_tar[s_t]
                #Building Node(Label)
                nodes = []
                for i, r in enumerate(RANK):
                    nodes.append(
                        [
                            (
                            f"{r}_{e}",nodes_num[r][nodes_name[r].index(e)],
                                {"color":"grey"}
                                ) 
                                for e in nodes_name[r]
                        ]
                        
                        )
            src_tar_df.to_csv(f"{des}/{SampleID}_flow.csv", index=False)

            #Preparing Sankey Diagram
            #Estimate fig size by the max number of vertical nodes (Mostly at genus level)
            max_nodes = max([len(e) for e in nodes])
            fig, ax = plt.subplots(1,1,figsize=(30, max(max_nodes/2*vertical_scale,10)))
            s = Sankey(flows=flows, 
                    nodes=nodes,
                    flow_color_mode='source',
                    node_opts=dict(
                                    label_format='{label} ({value:.0f})',
                                    label_opts=dict(fontsize=16),
                                    label_pos='right',
                                    ),
                    label_pad_x = 10,
                    scale=0.1)
            #Revise label after the sankey is established, this can avoid some problems caused by the confliction of label
            for tax in tax_list:
                s.find_node(tax)[0].label= "_".join(s.find_node(tax)[0].label.split("_")[1:])
            #Add title
            ax.set_title(f"{SampleID} Taxonomic Assignment",fontsize=25)
            s.draw(ax=ax)
            #Save the figure
            plt.savefig(f"{des}/{SampleID}_sankey.svg", dpi=300, bbox_inches='tight')
            #plt.close(fig)
# %%
