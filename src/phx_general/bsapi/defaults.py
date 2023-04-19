import os


class BSAPIBinaryNames:
    VAD = "vad"
    STT = "stt"


class PHXBinaries:
    ROOT = "/media/marvin/_projects/ASR/_bin"
    BSAPI = os.path.join(ROOT, "BSAPI", "build", "bin", "phxcmd")
    SCTK = os.path.join(ROOT, "SCTK-2.4.11", "bin")
    SRILM = os.path.join(ROOT, "Srilm-1.7.0", "bin")
    OPENFST = os.path.join(ROOT, "openfst-1.7.6", "src", "bin")
    OPENGRM = os.path.join(ROOT, "ngram-1.3.9", "src", "bin")


class BSAPIBinaryPaths:
    VAD = os.path.join(PHXBinaries.BSAPI, BSAPIBinaryNames.VAD)


class LM:
    default_order = 5
    use_knesser_ney = False
    use_unk = False


class Text:
    suffix = ".txt"


class BSAPISTT:
    dirname_decoder = "decoder"
    dirname_lmc = "lmc"
    dirname_vad = "VAD"
    dirname_dicts = "dicts"
    dirname_nn = "nn"
    dirname_xvec_acoustic = "ACOUSTIC"
    dirname_grammar = "grm"
    #
    basename_dictionary = "dictionary.txt"
    basename_g2p = "g2p.fst"
    basename_tied_list = "tied_list.txt"
    basename_acoustics = "acoustics.fst"
    basename_xvector_mean = "initxvec.txt"
    basename_graphemes = "graphemes"
    basename_nn = "nn.onnx"
    basename_mfcc = "mfcc.bscat"
    basename_classes = "classes.txt"
    basename_numeric = "numeric.pegjs"
    #
    relpath_xvector_mean = basename_xvector_mean
    relpath_graphemes = os.path.join(dirname_dicts, basename_graphemes)
    relpath_nn = os.path.join(dirname_nn, basename_nn)
    relpath_mfcc = os.path.join(dirname_nn, basename_mfcc)


class Dataset:
    test_keywords = "test_keywords.list"
