"""
Source Quality and Time-Based Filtering Engine.

Ensures only high-quality, relevant, and timely content reaches the user.

Filtering Pipeline:
1. Time Check: Articles within max_age_hours pass. Undated articles
   pass if they are topically relevant (exact date is not mandatory).
2. Tech/Science Topic Relevance: Title/summary MUST match at least
   one tech or science keyword to be included.
3. Content Quality: Reject spam, navigation pages, and empty articles.
"""

import logging
import re
from datetime import datetime, timedelta, UTC
from typing import List, Optional, Set

from src.core.types import Article, SourceTier
from src.core.protocol import SourceStatus, EventType
from src.core.events import event_bus

logger = logging.getLogger(__name__)


# =============================================================================
# TECH & SCIENCE KEYWORD SETS (used for topic relevance filtering)
# =============================================================================

# Core tech keywords
TECH_KEYWORDS: Set[str] = {
    # ── Computing & Software ──────────────────────────────────────────
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "neural network", "llm", "gpt", "transformer", "generative ai",
    "software", "hardware", "programming", "coding", "developer",
    "algorithm", "database", "api", "sdk", "framework",
    "cloud", "cloud computing", "saas", "paas", "iaas",
    "devops", "kubernetes", "docker", "microservice",
    "open source", "linux", "python", "rust", "javascript",
    "cybersecurity", "data breach", "malware",
    "ransomware", "vulnerability", "encryption", "zero-day",
    "blockchain", "crypto", "bitcoin", "ethereum", "web3",
    "quantum computing", "quantum", "qubit",
    "semiconductor", "chip", "processor", "gpu", "cpu", "nvidia",
    "amd", "intel", "tsmc", "arm",
    "5g", "6g", "wireless", "iot", "internet of things",
    "vr", "ar", "virtual reality", "augmented reality", "mixed reality",
    "metaverse", "spatial computing",
    "robotics", "robot", "automation", "autonomous",
    "drone", "self-driving", "autonomous vehicle",
    "data science", "big data", "analytics", "data engineering",
    "startup", "venture capital", "funding", "ipo",
    "fintech", "neobank", "digital payments",
    "technology", "tech industry", "tech company",
    "apple inc", "google", "microsoft", "amazon web services", "meta platforms", "tesla",
    "openai", "anthropic", "deepmind", "spacex",
    "samsung", "huawei", "alibaba", "tencent",

    # ── ADVANCED: AI / ML / NLP / CV ─────────────────────────────────
    "reinforcement learning", "supervised learning", "unsupervised learning",
    "federated learning", "transfer learning", "few-shot learning",
    "zero-shot learning", "self-supervised learning", "meta-learning",
    "multimodal ai", "diffusion model", "stable diffusion", "midjourney",
    "dall-e", "sora", "text-to-image", "text-to-video", "text-to-speech",
    "speech recognition", "natural language processing", "nlp",
    "computer vision", "object detection", "image segmentation",
    "sentiment analysis", "named entity recognition", "tokenization",
    "embedding", "vector database", "retrieval augmented generation", "rag",
    "fine-tuning", "prompt engineering", "chain-of-thought", "reasoning",
    "attention mechanism", "backpropagation", "gradient descent",
    "convolutional neural network", "cnn", "recurrent neural network", "rnn",
    "long short-term memory", "lstm", "graph neural network", "gnn",
    "generative adversarial network", "gan", "variational autoencoder", "vae",
    "large language model", "foundation model", "multimodal model",
    "mixture of experts", "moe", "parameter-efficient fine-tuning", "lora",
    "quantization", "model compression", "knowledge distillation",
    "ai safety", "alignment", "rlhf", "constitutional ai",
    "ai ethics", "bias in ai", "explainable ai", "xai",
    "ai regulation", "ai governance", "ai policy",
    "agi", "artificial general intelligence", "superintelligence",
    "hugging face", "pytorch", "tensorflow", "jax", "keras",
    "langchain", "llamaindex", "autogen", "crewai",
    "copilot", "chatbot", "virtual assistant", "ai agent",
    "synthetic data", "data augmentation", "active learning",
    "anomaly detection", "predictive analytics", "recommendation system",
    "edge ai", "tinyml", "on-device inference", "model serving",
    "mlops", "ai infrastructure", "gpu cluster", "training run",
    "inference", "latency", "throughput", "benchmark",
    "hallucination", "grounding", "tool use", "function calling",
    "context window", "token limit", "temperature", "top-k", "top-p",
    "open-weight model", "llama", "mistral", "gemini", "claude",
    "phi", "qwen", "deepseek", "grok",

    # ── ADVANCED: Cloud / Infra / DevOps ─────────────────────────────
    "serverless", "lambda", "containerization", "orchestration",
    "ci/cd", "continuous integration", "continuous deployment",
    "infrastructure as code", "terraform", "ansible", "puppet",
    "service mesh", "istio", "envoy", "sidecar",
    "load balancer", "reverse proxy", "cdn", "content delivery network",
    "object storage", "s3", "blob storage", "data lake", "data warehouse",
    "stream processing", "apache kafka", "apache spark", "apache flink",
    "apache hadoop", "mapreduce", "etl", "elt", "data pipeline",
    "graph database", "neo4j", "time-series database", "influxdb",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "graphql", "rest api", "grpc", "websocket", "server-sent events",
    "oauth", "jwt", "saml", "identity provider", "iam",
    "zero trust", "soc", "siem", "threat intelligence", "incident response",
    "penetration testing", "bug bounty", "cve", "exploit", "patch",
    "firewall", "ids", "ips", "endpoint detection", "edr",
    "phishing", "social engineering", "apt", "advanced persistent threat",
    "supply chain attack", "log4j", "heartbleed", "spectre", "meltdown",
    "homomorphic encryption", "post-quantum cryptography", "lattice-based",
    "secure enclave", "trusted execution environment", "tee",
    "confidential computing", "differential privacy",
    "web application firewall", "waf", "ddos", "botnet",

    # ── ADVANCED: Blockchain / Web3 / DeFi ───────────────────────────
    "defi", "decentralized finance", "smart contract", "solidity",
    "nft", "non-fungible token", "dao", "decentralized autonomous organization",
    "layer 1", "layer 2", "rollup", "zk-snark", "zk-stark",
    "zero-knowledge proof", "consensus mechanism", "proof of stake",
    "proof of work", "sharding", "cross-chain", "interoperability",
    "tokenomics", "staking", "yield farming", "liquidity pool",
    "dex", "decentralized exchange", "amm", "automated market maker",
    "stablecoin", "cbdc", "central bank digital currency",
    "solana", "cardano", "polkadot", "avalanche", "cosmos",
    "chainlink", "uniswap", "aave", "makerdao",
    "web3 infrastructure", "ipfs", "filecoin", "decentralized storage",
    "digital identity", "self-sovereign identity", "verifiable credential",
    "regulation crypto", "sec crypto", "crypto regulation",

    # ── ADVANCED: Quantum ────────────────────────────────────────────
    "quantum supremacy", "quantum advantage", "quantum error correction",
    "quantum entanglement", "quantum superposition", "quantum teleportation",
    "quantum annealing", "quantum simulation", "quantum algorithm",
    "shor's algorithm", "grover's algorithm", "quantum fourier transform",
    "topological qubit", "superconducting qubit", "trapped ion",
    "photonic quantum", "quantum networking", "quantum internet",
    "quantum key distribution", "qkd", "quantum sensing",
    "ibm quantum", "google quantum ai", "ionq", "rigetti", "d-wave",
    "quantum volume", "quantum fidelity", "decoherence",
    "quantum machine learning", "quantum chemistry", "quantum optimization",

    # ── ADVANCED: Semiconductor / Hardware ───────────────────────────
    "fabrication", "lithography", "euv", "extreme ultraviolet",
    "transistor", "finfet", "gate-all-around", "gaa", "nanosheet",
    "chiplet", "advanced packaging", "3d stacking", "through-silicon via",
    "system on chip", "soc", "fpga", "asic", "risc-v",
    "neural processing unit", "npu", "tensor processing unit", "tpu",
    "wafer", "silicon", "gallium nitride", "gan", "silicon carbide", "sic",
    "photonics", "silicon photonics", "optical interconnect",
    "memory", "dram", "nand", "hbm", "high bandwidth memory",
    "chip design", "eda", "electronic design automation", "synopsys", "cadence",
    "asml", "qualcomm", "broadcom", "mediatek", "marvell",
    "chip shortage", "fab", "foundry", "semiconductor supply chain",
    "neuromorphic computing", "spiking neural network", "memristor",
    "analog computing", "in-memory computing", "compute-in-memory",

    # ── ADVANCED: Networking / Telecom ───────────────────────────────
    "network slicing", "massive mimo", "beamforming", "millimeter wave",
    "sub-6 ghz", "small cell", "open ran", "o-ran",
    "satellite internet", "low earth orbit", "leo", "starlink",
    "edge computing", "fog computing", "mec", "multi-access edge computing",
    "software defined networking", "sdn", "network function virtualization", "nfv",
    "wifi 7", "wifi 6e", "thread", "matter", "zigbee", "z-wave",
    "bluetooth", "nfc", "ultra-wideband", "uwb",
    "tcp/ip", "http/3", "quic", "dns", "bgp",
    "network security", "tls", "ssl", "certificate authority",

    # ── ADVANCED: Robotics / Autonomous ──────────────────────────────
    "humanoid robot", "soft robotics", "swarm robotics",
    "robot operating system", "ros", "ros2",
    "simultaneous localization and mapping", "slam",
    "lidar", "radar", "sensor fusion", "perception",
    "path planning", "motion planning", "inverse kinematics",
    "computer-controlled", "cnc", "additive manufacturing", "3d printing",
    "digital twin", "industrial automation", "plc", "scada",
    "collaborative robot", "cobot", "exoskeleton",
    "warehouse automation", "logistics automation",
    "agricultural robotics", "surgical robot", "da vinci",
    "autonomous shipping", "autonomous truck", "waymo", "cruise",
    "flying taxi", "evtol", "urban air mobility",
    "underwater robot", "rov", "auv",

    # ── Science & Research ────────────────────────────────────────────
    "science", "scientific", "research", "discovery", "breakthrough",
    "experiment", "hypothesis", "peer-reviewed", "publication",
    "physics", "astrophysics", "cosmology", "particle physics",
    "dark matter", "dark energy", "gravitational wave",
    "higgs", "cern", "lhc", "fusion", "nuclear",
    "biology", "genetics", "genomics", "crispr", "gene editing",
    "dna", "rna", "protein", "cell", "stem cell", "neuroscience",
    "neuron", "brain", "cognitive", "evolution",
    "chemistry", "chemical", "molecule", "catalyst", "polymer",
    "materials science", "nanotechnology", "graphene",
    "biotechnology", "biotech", "pharma", "pharmaceutical",
    "vaccine", "clinical trial", "fda", "drug",
    "medicine", "medical", "health tech", "healthtech",
    "space", "nasa", "esa", "satellite", "telescope",
    "mars", "moon", "asteroid", "exoplanet", "cosmic",
    "climate change", "climate science", "renewable energy", "solar energy", "solar panel",
    "wind energy", "battery", "ev", "electric vehicle",
    "carbon capture", "sustainability", "green tech",
    "ecology", "biodiversity", "conservation", "species",
    "ocean", "marine", "geoscience", "geology", "earthquake",
    "mathematics", "theorem", "proof", "computation",
    "engineering", "aerospace", "mechanical", "electrical",

    # ── ADVANCED: Physics / Astronomy ────────────────────────────────
    "string theory", "loop quantum gravity", "standard model",
    "supersymmetry", "antimatter", "neutrino", "quark", "lepton",
    "boson", "fermion", "photon", "graviton",
    "black hole", "neutron star", "pulsar", "magnetar",
    "supernova", "gamma-ray burst", "cosmic microwave background", "cmb",
    "james webb", "jwst", "hubble", "event horizon telescope",
    "laser interferometer", "ligo", "virgo", "kagra",
    "plasma physics", "magnetohydrodynamics", "tokamak", "stellarator",
    "iter", "inertial confinement", "laser fusion", "ignition",
    "nuclear fission", "nuclear waste", "small modular reactor", "smr",
    "particle accelerator", "synchrotron", "free-electron laser",
    "condensed matter", "superconductor", "superconductivity",
    "topological insulator", "quantum hall effect",
    "general relativity", "special relativity", "spacetime",
    "cosmological constant", "inflation", "multiverse",
    "exoplanet atmosphere", "biosignature", "astrobiology",
    "seti", "fermi paradox", "drake equation",
    "solar system", "jupiter", "saturn", "titan", "europa",
    "artemis", "gateway", "lunar base", "space station", "iss",
    "space debris", "planetary defense", "near-earth object",
    "gravitational lensing", "redshift", "spectroscopy",

    # ── ADVANCED: Biology / Genetics / Medicine ──────────────────────
    "proteomics", "metabolomics", "transcriptomics", "epigenetics",
    "methylation", "histone", "chromatin", "gene expression",
    "mrna", "sirna", "mirna", "gene therapy", "gene drive",
    "base editing", "prime editing", "cas9", "cas12", "cas13",
    "synthetic biology", "bioengineering", "bioinformatics",
    "protein folding", "alphafold", "protein structure",
    "drug discovery", "drug design", "molecular docking",
    "high-throughput screening", "combinatorial chemistry",
    "antibody", "monoclonal antibody", "immunotherapy",
    "car-t cell", "checkpoint inhibitor", "oncology",
    "tumor", "cancer", "metastasis", "biomarker",
    "precision medicine", "personalized medicine", "pharmacogenomics",
    "microbiome", "gut bacteria", "probiotic",
    "organoid", "organ-on-chip", "tissue engineering",
    "regenerative medicine", "3d bioprinting",
    "epidemiology", "pandemic", "pathogen", "virology",
    "coronavirus", "influenza", "antibiotic resistance",
    "neurodegenerative", "alzheimer", "parkinson", "als",
    "brain-computer interface", "bci", "neuralink", "neurotechnology",
    "connectome", "optogenetics", "electrophysiology",
    "clinical genomics", "whole genome sequencing", "wgs",
    "liquid biopsy", "circulating tumor dna", "ctdna",
    "fda approval", "phase 1", "phase 2", "phase 3",
    "randomized controlled trial", "rct", "meta-analysis",
    "systematic review", "cohort study", "longitudinal study",
    "telemedicine", "digital health", "wearable health",
    "medical imaging", "mri", "ct scan", "pet scan", "ultrasound",
    "radiology ai", "pathology ai", "diagnostic ai",
    "robotic surgery", "minimally invasive", "laparoscopic",
    "global health", "who", "cdc", "nih",

    # ── ADVANCED: Chemistry / Materials ──────────────────────────────
    "organic chemistry", "inorganic chemistry", "physical chemistry",
    "analytical chemistry", "computational chemistry",
    "electrochemistry", "photochemistry", "supramolecular",
    "metal-organic framework", "mof", "covalent organic framework", "cof",
    "perovskite", "quantum dot", "carbon nanotube", "fullerene",
    "2d materials", "transition metal dichalcogenide", "tmdc",
    "mxene", "borophene", "phosphorene",
    "metamaterial", "photonic crystal", "plasmonics",
    "shape memory alloy", "self-healing material", "smart material",
    "biodegradable", "biocompatible", "biomaterial",
    "ceramic", "composite", "alloy", "superconductor material",
    "thin film", "epitaxy", "chemical vapor deposition", "cvd",
    "atomic layer deposition", "ald", "sputtering",
    "x-ray diffraction", "xrd", "electron microscopy", "sem", "tem",
    "mass spectrometry", "chromatography", "nmr",
    "density functional theory", "dft", "molecular dynamics",
    "polymer science", "elastomer", "thermoplastic", "thermoset",
    "green chemistry", "sustainable chemistry", "circular economy",
    "hydrogen economy", "green hydrogen", "electrolyzer", "fuel cell",
    "lithium-ion", "solid-state battery", "sodium-ion", "flow battery",
    "supercapacitor", "energy harvesting", "piezoelectric",
    "thermoelectric", "photovoltaic", "perovskite solar cell",
    "organic solar cell", "tandem solar cell",
    "carbon fiber", "kevlar", "aerogel",

    # ── ADVANCED: Climate / Energy / Environment ─────────────────────
    "global warming", "greenhouse gas", "co2", "methane", "nitrous oxide",
    "carbon footprint", "carbon offset", "carbon credit", "carbon tax",
    "net zero", "decarbonization", "energy transition",
    "paris agreement", "cop28", "cop29", "cop30", "ipcc",
    "renewable energy", "solar panel", "wind turbine", "offshore wind",
    "geothermal", "hydropower", "tidal energy", "wave energy",
    "bioenergy", "biomass", "biofuel", "biodiesel", "ethanol",
    "nuclear energy", "nuclear power", "fusion energy",
    "energy storage", "grid-scale storage", "pumped hydro",
    "smart grid", "demand response", "virtual power plant",
    "electric grid", "power electronics", "inverter",
    "electric vehicle", "battery electric vehicle", "bev",
    "plug-in hybrid", "phev", "hydrogen fuel cell vehicle",
    "ev charging", "fast charging", "vehicle-to-grid", "v2g",
    "sustainable aviation fuel", "saf", "electric aircraft",
    "green shipping", "maritime decarbonization",
    "deforestation", "reforestation", "afforestation",
    "soil carbon", "regenerative agriculture", "precision agriculture",
    "ocean acidification", "sea level rise", "ice sheet",
    "permafrost", "arctic", "antarctic", "glacier",
    "extreme weather", "heatwave", "drought", "flood", "wildfire",
    "air quality", "particulate matter", "pm2.5", "ozone",
    "water scarcity", "desalination", "water treatment",
    "waste management", "recycling", "upcycling", "zero waste",
    "plastic pollution", "microplastic", "ocean cleanup",
    "biodiversity loss", "sixth extinction", "habitat loss",
    "invasive species", "wildlife trafficking",
    "environmental monitoring", "remote sensing", "earth observation",
    "copernicus", "landsat", "sentinel",

    # ── ADVANCED: Mathematics ────────────────────────────────────────
    "number theory", "algebra", "topology", "geometry",
    "differential equations", "partial differential equation", "pde",
    "linear algebra", "abstract algebra", "group theory", "ring theory",
    "category theory", "homological algebra", "algebraic geometry",
    "differential geometry", "riemannian geometry",
    "combinatorics", "graph theory", "discrete mathematics",
    "probability", "statistics", "bayesian", "stochastic",
    "markov chain", "monte carlo", "random matrix",
    "optimization", "convex optimization", "linear programming",
    "game theory", "nash equilibrium", "mechanism design",
    "cryptography", "elliptic curve", "rsa", "lattice cryptography",
    "information theory", "entropy", "coding theory",
    "dynamical systems", "chaos theory", "fractal",
    "numerical analysis", "finite element method", "fem",
    "computational complexity", "p vs np", "turing machine",
    "automated theorem proving", "formal verification", "lean", "coq",
    "mathematical logic", "set theory", "model theory",
    "riemann hypothesis", "goldbach conjecture", "twin prime",
    "langlands program", "hodge conjecture", "birch conjecture",
    "knot theory", "manifold", "fiber bundle",

    # ── ADVANCED: Engineering ────────────────────────────────────────
    "structural engineering", "civil engineering", "geotechnical",
    "fluid dynamics", "computational fluid dynamics", "cfd",
    "thermodynamics", "heat transfer", "combustion",
    "control systems", "pid controller", "state-space",
    "signal processing", "digital signal processing", "dsp",
    "fourier transform", "wavelet", "kalman filter",
    "electromagnetic", "antenna", "rf", "microwave",
    "power systems", "power electronics", "motor drive",
    "vlsi", "embedded systems", "rtos", "firmware",
    "cad", "cam", "cae", "finite element analysis", "fea",
    "systems engineering", "reliability engineering",
    "manufacturing", "lean manufacturing", "six sigma",
    "supply chain", "logistics", "operations research",
    "biomedical engineering", "prosthetics", "implant",
    "environmental engineering", "wastewater", "air filtration",
    "nuclear engineering", "radiation", "reactor design",
    "marine engineering", "naval architecture",
    "mining engineering", "petroleum engineering",
    "textile engineering", "food science",

    # ── Knowledge sources ─────────────────────────────────────────────
    "wikipedia", "arxiv", "nature", "ieee", "acm",
    "journal", "preprint", "paper", "study", "findings",

    # ── ADVANCED: Knowledge / Academic Sources ───────────────────────
    "pubmed", "medline", "scopus", "web of science",
    "google scholar", "semantic scholar", "crossref", "doi",
    "biorxiv", "medrxiv", "chemrxiv", "engrxiv", "psyarxiv",
    "ssrn", "researchgate", "academia.edu",
    "cell", "lancet", "nejm", "jama", "bmj", "pnas",
    "physical review", "physical review letters", "prl",
    "journal of the american chemical society", "jacs",
    "angewandte chemie", "chemical reviews",
    "proceedings of the national academy",
    "science advances", "nature communications", "nature methods",
    "nature biotechnology", "nature medicine", "nature physics",
    "nature chemistry", "nature materials", "nature neuroscience",
    "nature machine intelligence", "nature computational science",
    "cell reports", "molecular cell", "current biology",
    "the lancet oncology", "the lancet neurology",
    "annals of internal medicine", "annals of mathematics",
    "journal of machine learning research", "jmlr",
    "advances in neural information processing systems", "neurips",
    "icml", "iclr", "cvpr", "eccv", "iccv", "acl", "emnlp",
    "aaai", "ijcai", "sigir", "kdd", "www conference",
    "mit technology review", "scientific american", "new scientist",
    "quanta magazine", "nautilus", "aeon",
    "proceedings of the ieee", "ieee transactions",
    "acm computing surveys", "acm transactions",
    "springer", "elsevier", "wiley", "taylor and francis",
    "oxford university press", "cambridge university press",
    "annual reviews", "frontiers", "plos", "plos one",
    "elife", "peerj", "mdpi",
    "citation", "impact factor", "h-index", "bibliometrics",
    "open access", "creative commons", "preprint server",
    "retraction", "reproducibility", "replication crisis",

    # ── Consumer Electronics / Apps ──────────────────────────────────
    "app", "iphone", "ipad", "macbook", "pixel", "galaxy",
    "smartphone", "laptop", "tablet", "wearable", "smartwatch",
    "systematic review", "cochrane", "prisma",
}

# Spam / low-quality indicators
SPAM_PATTERNS: Set[str] = {
    # ── Original ──────────────────────────────────────────────────────
    "click here", "subscribe now", "sign up free", "limited time offer",
    "buy now", "download free", "earn money", "work from home",
    "best deals", "coupon code", "promo code", "affiliate",
    "sponsored content", "advertisement", "casino", "gambling",
    "weight loss", "diet pill", "dating site",

    # ── Financial / Money Scams ───────────────────────────────────────
    "make money fast", "get rich quick", "passive income",
    "financial freedom", "millionaire mindset", "money back guarantee",
    "no credit check", "no hidden fees", "no obligation",
    "free money", "cash prize", "you've won", "congratulations you won",
    "claim your prize", "lottery winner", "sweepstakes",
    "wire transfer", "western union", "money order",
    "cryptocurrency giveaway", "double your bitcoin", "free crypto",
    "investment opportunity", "guaranteed returns", "high yield",
    "ponzi", "pyramid scheme", "multi-level marketing", "mlm",
    "forex trading", "day trading signal", "pump and dump",
    "debt relief", "debt consolidation", "settle your debt",
    "tax refund", "irs", "tax relief", "unclaimed money",
    "inheritance fund", "beneficiary", "next of kin",
    "nigerian prince", "advance fee", "419 scam",

    # ── Urgency / Pressure ────────────────────────────────────────────
    "act now", "hurry", "don't miss out", "last chance",
    "once in a lifetime", "limited spots", "only a few left",
    "expires today", "offer ends", "while supplies last",
    "order now", "call now", "don't delay", "time is running out",
    "exclusive offer", "secret deal", "insider access",
    "be the first", "early bird", "flash sale",
    "clearance", "going out of business", "final notice",
    "urgent", "immediate action required", "respond now",
    "your account will be closed", "verify your account",
    "suspicious activity detected", "unusual login",

    # ── Health / Miracle Cures ────────────────────────────────────────
    "miracle cure", "secret remedy", "ancient remedy",
    "doctors hate this", "one weird trick", "lose 10 pounds",
    "burn fat fast", "flat belly", "six pack abs",
    "anti-aging", "reverse aging", "look 10 years younger",
    "enhancement", "male enhancement", "enlargement",
    "prescription free", "no prescription needed",
    "pharmacy online", "cheap viagra", "cheap cialis",
    "herbal supplement", "natural cure", "detox",
    "cleanse", "colon cleanse", "parasite cleanse",
    "essential oil cure", "homeopathic", "quantum healing",
    "cancer cure", "cure diabetes", "cure hiv",
    "vaccine misinformation", "vaccine dangerous", "vaccine causes",
    "5g causes", "chemtrails", "flat earth",

    # ── Adult / Explicit ──────────────────────────────────────────────
    "adult content", "xxx", "porn", "nude", "naked",
    "escort", "hookup", "sex chat", "cam girl",
    "erotic", "fetish", "nsfw",

    # ── Phishing / Social Engineering ─────────────────────────────────
    "reset your password", "confirm your identity",
    "update your payment", "billing issue", "payment failed",
    "your package is waiting", "delivery failed", "track your package",
    "you have a new message", "unread notification",
    "friend request", "someone viewed your profile",
    "your subscription is expiring", "renew now",
    "prince", "diplomat", "ambassador", "overseas",
    "confidential", "strictly private", "for your eyes only",
    "kindly", "dear sir/madam", "dear friend",
    "god bless", "pray", "testimony",

    # ── Non-Tech / Lifestyle / Off-Topic Blacklist ────────────────────
    "cafe", "cafes", "vietnamese cafes", "coffee shop", "coffees",
    "sandwich", "sandwiches", "restaurant", "restaurants", "eatery",
    "brunch", "dining", "recipes", "cocktail", "cocktails", "bakery",
    "wine tasting", "brewery", "tasting menu", "foodie", "fine dining",
    "pastry", "croissant", "ramen", "pizzeria", "burger", "pizza",
    "house prices", "apartment rent", "real estate", "mortgage rates",
    "housing market", "property market", "landlord", "condo sales",
    "horoscope", "astrology", "dating advice", "skincare routine",
    "celebrity gossip", "red carpet", "fashion week", "makeup tips",
    "premier league", "nfl recap", "nba finals", "cricket score",
    "golf tournament", "tennis match", "traffic accident", "highway closure",
    "burglary", "armed robbery", "police arrest", "local crime",

    # ── Fake Tech / Scareware ─────────────────────────────────────────
    "your computer is infected", "virus detected",
    "system error", "registry cleaner", "pc optimizer",
    "speed up your computer", "clean your registry",
    "driver updater", "outdated drivers",
    "your iphone is hacked", "your android is infected",
    "security alert", "critical warning",
    "download this tool", "install now", "update required",
    "browser hijacker", "adware", "spyware remover",
    "tech support scam", "call microsoft", "call apple support",

    # ── Gambling / Betting ────────────────────────────────────────────
    "online casino", "sports betting", "bet now",
    "poker online", "slot machine", "jackpot",
    "free spins", "no deposit bonus", "welcome bonus",
    "bookmaker", "odds", "parlay", "accumulator",
    "live dealer", "roulette", "blackjack",

    # ── Misc Spam ─────────────────────────────────────────────────────
    "unsubscribe", "opt out", "remove me",
    "this is not spam", "not a scam", "legitimate offer",
    "as seen on tv", "as seen on", "tv offer",
    "satisfaction guaranteed", "risk free", "try for free",
    "no strings attached", "cancel anytime",
    "terms and conditions apply", "see details",
    "disclaimer", "results may vary", "individual results",
    "testimonials", "before and after", "real results",
    "celebrity endorsement", "doctor recommended",
    "award winning", "voted number one", "reader's choice",
}

# ── AMBIGUOUS KEYWORDS ───────────────────────────────────────────────
# These words appear in tech contexts but ALSO commonly in non-tech contexts.
# When a title's ONLY keyword matches are from this set, require 2+ matches
# to avoid false positives like "cloud-like coffees" or "carbon offsets".
AMBIGUOUS_KEYWORDS: Set[str] = {
    "cloud", "app", "cell", "chip", "drug", "battery", "satellite",
    "carbon", "fusion", "nuclear", "space", "mars", "moon",
    "engineering", "manufacturing", "startup", "funding", "ipo",
    "discovery", "breakthrough", "research", "study", "findings",
    "paper", "journal", "science", "scientific", "experiment",
    "evolution", "species", "conservation", "ocean", "marine",
    "ecology", "climate change", "sustainability", "green",
    "health", "medical", "medicine", "vaccine", "protein",
    "brain", "neural", "network", "model", "data",
    "digital", "platform", "system", "intelligence",
    "memory", "technology", "automation", "patent",
    "energy", "power", "grid", "electric", "solar",
    "wind", "oil", "gas", "fuel", "pipeline",
}

# ── NON-TECH REJECTION PATTERNS (title-level) ──────────────────────────
# If ANY of these appear in the title, reject immediately regardless of tech keywords.
NON_TECH_TITLE_PATTERNS: Set[str] = {
    # Food & Dining
    "cafe", "cafes", "coffee shop", "coffees", "sandwich", "sandwiches",
    "restaurant", "restaurants", "eatery", "brunch", "dining", "recipe",
    "recipes", "bakery", "pastry", "croissant", "wine tasting", "brewery",
    "tasting menu", "foodie", "fine dining", "ramen", "pizzeria",
    "burger", "pizza", "cocktail", "cocktails", "sushi", "vegan food",
    # Real estate
    "house prices", "apartment rent", "real estate", "mortgage rates",
    "housing market", "property market", "landlord", "condo sales",
    # Lifestyle / Entertainment
    "horoscope", "astrology", "dating advice", "skincare routine",
    "celebrity gossip", "red carpet", "fashion week", "makeup tips",
    "reality tv", "love island", "bachelor", "bachelorette",
    # Sports
    "premier league", "nfl recap", "nba finals", "cricket score",
    "golf tournament", "tennis match", "world cup", "champions league",
    "super bowl", "playoff", "matchday", "hat trick", "home run",
    # Local crime / incidents
    "traffic accident", "highway closure", "burglary", "armed robbery",
    "police arrest", "local crime", "stabbing", "shooting suspect",
    # Politics (without tech angle)
    "election results", "campaign trail", "ballot", "impeach",
    "windfall tax", "tax on big oil", "labor party", "conservative party",
    "parliament debate", "senate vote", "congress vote",
    # Finance / Stock (without tech company)
    "stock fair value", "earnings call", "form 425", "form 10-k",
    "sec filing", "dividend", "market cap", "stock split",
    "trading signal", "forex", "commodity price", "crude oil",
    "gold price", "bond yield", "interest rate hike",
    # Shopping deals
    "best deal", "best deals", "discount code", "booster box",
    "save now", "price drop", "pokémon tcg", "pokemon tcg",
    # Weather / almanac
    "moon phase", "weather forecast", "pollen count", "tide table",
    "sunrise", "sunset", "lunar calendar",
}

# ── JUNK SOURCE DOMAINS (discovered via Google News, reject on sight) ──
JUNK_SOURCE_DOMAINS: Set[str] = {
    "streetinsider.com", "finance.biggo.com", "syracuse.com",
    "thedailyupside.com", "linkedin.com",
}

# Generic navigation titles to reject
GENERIC_TITLES: Set[str] = {
    # ── Original ──────────────────────────────────────────────────────
    "home", "login", "signup", "subscribe", "page not found",
    "404", "error", "untitled", "test", "example",
    "cookie policy", "privacy policy", "terms of service",
    "contact us", "about us", "careers", "sitemap",

    # ── Navigation / Structural ───────────────────────────────────────
    "main menu", "navigation", "menu", "header", "footer",
    "sidebar", "breadcrumb", "pagination", "next page", "previous page",
    "back to top", "scroll to top", "read more", "see all",
    "view all", "show more", "load more", "see more",
    "table of contents", "index", "directory", "archive",
    "categories", "tags", "labels", "filter", "sort",
    "search", "search results", "no results found",
    "advanced search", "search page",

    # ── Legal / Compliance ────────────────────────────────────────────
    "terms and conditions", "terms of use", "legal notice",
    "legal", "disclaimer", "copyright", "copyright notice",
    "dmca", "dmca policy", "intellectual property",
    "gdpr", "data protection", "data privacy",
    "cookie consent", "cookie settings", "manage cookies",
    "do not sell my information", "ccpa",
    "acceptable use policy", "community guidelines",
    "code of conduct", "editorial policy",
    "accessibility", "accessibility statement",
    "modern slavery statement", "ethics policy",

    # ── User Account ──────────────────────────────────────────────────
    "register", "sign in", "sign out", "log out", "log in",
    "forgot password", "reset password", "change password",
    "my account", "my profile", "profile", "account settings",
    "dashboard", "settings", "preferences", "notifications",
    "billing", "payment methods", "subscription", "plan",
    "upgrade", "downgrade", "cancel subscription",
    "two-factor authentication", "2fa", "security settings",
    "delete account", "deactivate account",

    # ── E-commerce Generic ────────────────────────────────────────────
    "cart", "shopping cart", "checkout", "order confirmation",
    "order status", "track order", "shipping", "returns",
    "refund policy", "exchange policy", "warranty",
    "faq", "frequently asked questions", "help", "support",
    "help center", "knowledge base", "documentation",
    "api docs", "developer docs", "changelog", "release notes",
    "status page", "system status", "uptime",

    # ── Boilerplate / Placeholder ─────────────────────────────────────
    "lorem ipsum", "placeholder", "coming soon", "under construction",
    "work in progress", "draft", "temp", "temporary",
    "sample", "demo", "hello world", "foo bar",
    "page 1", "page 2", "page 3",
    "new page", "new post", "new article",
    "default", "default page", "default title",
    "null", "none", "n/a", "tbd", "todo",
    "undefined", "empty", "blank",

    # ── Social / Sharing ──────────────────────────────────────────────
    "share", "share this", "share on facebook", "share on twitter",
    "tweet", "pin it", "share on linkedin",
    "follow us", "like us", "subscribe to our channel",
    "newsletter", "email newsletter", "weekly digest",
    "social media", "social links", "connect with us",

    # ── Ads / Sponsored ───────────────────────────────────────────────
    "sponsored", "promoted", "paid partnership",
    "advertise with us", "media kit", "press kit",
    "brand guidelines", "logo download",
    "affiliate disclosure", "sponsored post",
    "native advertising", "content partnership",

    # ── Error / Status ────────────────────────────────────────────────
    "500", "502", "503", "403", "401",
    "internal server error", "bad gateway", "service unavailable",
    "forbidden", "unauthorized", "access denied",
    "maintenance", "under maintenance", "temporarily unavailable",
    "rate limited", "too many requests",
    "timeout", "connection error", "network error",

    # ── Misc Generic ──────────────────────────────────────────────────
    "welcome", "hello", "thank you", "thanks",
    "congratulations", "success", "confirmed",
    "loading", "please wait", "processing",
    "redirect", "redirecting", "you are being redirected",
    "print", "print this page", "email this page",
    "download", "download pdf", "view pdf",
    "rss", "feed", "atom", "xml",
    "robots.txt", "humans.txt", "security.txt",
    "webmaster", "admin", "administrator",
    "staff", "team", "our team", "leadership",
    "investors", "investor relations", "press",
    "press releases", "newsroom", "media",
    "blog", "news", "articles", "posts",
    "events", "calendar", "schedule",
    "gallery", "photos", "videos", "media library",
    "resources", "downloads", "tools",
    "partners", "partnerships", "integrations",
    "testimonials", "reviews", "ratings",
    "pricing", "plans", "features", "comparison",
}


class SourceQualityFilter:
    """
    Advanced filter for source quality, topic relevance, and time freshness.
    
    Filtering strategy:
    - 72-hour window articles get TOP priority in the feed
    - Undated but topically relevant articles are ALLOWED (not rejected)
    - Non-tech/science articles are REJECTED regardless of date
    - Spam and navigation pages are REJECTED
    """
    
    def __init__(self, strict_mode: bool = True, max_age_hours: int = 72):
        self.strict_mode = strict_mode
        self.max_age_hours = max_age_hours
        self._source_reliability = {}  # Map source domain to reliability score (0.0 - 1.0)
        
        # Pre-compile keyword patterns for fast matching
        # Sort by length descending so multi-word phrases are matched first
        sorted_keywords = sorted(TECH_KEYWORDS, key=len, reverse=True)
        # Build a single regex with word boundaries for efficiency
        escaped = [re.escape(kw) for kw in sorted_keywords]
        self._tech_pattern = re.compile(
            r'\b(?:' + '|'.join(escaped) + r')\b',
            re.IGNORECASE
        )
        
        # Pre-compile spam patterns into a single regex for O(1) matching
        # instead of iterating 257 patterns per article
        sorted_spam = sorted(SPAM_PATTERNS, key=len, reverse=True)
        escaped_spam = [re.escape(sp) for sp in sorted_spam]
        self._spam_pattern = re.compile(
            r'(?:' + '|'.join(escaped_spam) + r')',
            re.IGNORECASE
        )
        
        self._generic_titles = GENERIC_TITLES

    
    def filter_articles(self, articles: List[Article], max_age_hours: int = None) -> List[Article]:
        """
        Filter articles based on topic relevance, time freshness, and quality.
        
        Strategy:
        - Articles within max_age_hours AND topically relevant → PASS
        - Undated articles that are topically relevant → PASS (lower priority)
        - Non-tech/science articles → REJECT
        - Spam/garbage → REJECT
        
        Args:
            articles: List of articles to filter
            max_age_hours: Maximum age in hours (defaults to self.max_age_hours)
            
        Returns:
            Filtered list of articles
        """
        import time
        t_start = time.perf_counter()
        max_age = max_age_hours or self.max_age_hours
        filtered = []
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=max_age)
        
        rejected_reasons = {"stale": 0, "not_tech": 0, "spam": 0, "low_quality": 0}
        
        for article in articles:
            # 1. Content Quality Check (title length, generic pages, spam)
            quality_result = self._check_quality(article)
            if quality_result == "spam":
                rejected_reasons["spam"] += 1
                continue
            elif quality_result == "low_quality":
                rejected_reasons["low_quality"] += 1
                continue
            
            # 2. Tech/Science Topic Relevance (MANDATORY)
            if not self._is_tech_science_relevant(article):
                rejected_reasons["not_tech"] += 1
                continue
            
            # 3. Time Check (flexible — undated articles pass if topically relevant)
            time_status = self._check_timeliness(article, cutoff)
            if time_status == "stale":
                # Dated and too old → reject
                rejected_reasons["stale"] += 1
                continue
            # "fresh" or "undated" → both pass (undated gets lower sort priority later)
            
            filtered.append(article)
        
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        logger.info(
            f"⏱️ [{elapsed_ms:.1f}ms] 🛡️ Quality Filter: {len(articles)} → {len(filtered)} articles "
            f"(rejected: stale={rejected_reasons['stale']}, "
            f"not_tech={rejected_reasons['not_tech']}, "
            f"spam={rejected_reasons['spam']}, "
            f"low_quality={rejected_reasons['low_quality']})"
        )
        return filtered

    def _check_timeliness(self, article: Article, cutoff: datetime) -> str:
        """
        Check article timeliness.
        
        Returns:
            "fresh" — has a date and it's within the window
            "undated" — no date available (allowed if topically relevant)
            "stale" — has a date and it's too old
        """
        # Prefer published_at, fall back to scraped_at
        timestamp = article.published_at or article.scraped_at
        
        if not timestamp:
            return "undated"  # No date — allow if topically relevant
            
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
            
        if timestamp >= cutoff:
            return "fresh"
        else:
            return "stale"

    def _is_tech_science_relevant(self, article: Article) -> bool:
        """
        Check if article is about tech or science topics.
        
        Multi-tier check with ambiguous keyword handling:
        - Pre-check: Reject if title matches NON_TECH_TITLE_PATTERNS
        - Pre-check: Reject if source is from JUNK_SOURCE_DOMAINS
        - Tier 1: Title has 1+ non-ambiguous tech keyword → PASS
        - Tier 1b: Title has ONLY ambiguous keywords → require 2+ unique matches
        - Tier 2: No title match → require 2+ unique keywords in combined text
        - Otherwise → REJECT
        """
        title = (article.title or "").lower()
        source = (article.source or "").lower()
        url = (article.url or "").lower()

        # Pre-check 1: Reject if title matches non-tech patterns
        for pattern in NON_TECH_TITLE_PATTERNS:
            if pattern in title:
                return False

        # Pre-check 2: Reject if source domain is known junk
        for domain in JUNK_SOURCE_DOMAINS:
            if domain in url or domain in source:
                return False

        # Tier 1: Title contains tech keyword(s)
        if title and len(title) >= 10:
            title_matches = self._tech_pattern.findall(title)
            if title_matches:
                unique_title_kws = set(m.lower() for m in title_matches)
                # Check if ALL matched keywords are ambiguous
                non_ambiguous = unique_title_kws - AMBIGUOUS_KEYWORDS
                if non_ambiguous:
                    # At least one strong tech keyword in title → PASS
                    return True
                elif len(unique_title_kws) >= 2:
                    # Multiple ambiguous keywords together → likely tech (e.g., "cloud computing")
                    return True
                # else: single ambiguous keyword only → fall through to Tier 2
        
        # Tier 2: Title had no match or only ambiguous match — require 2+ matches in combined text
        text_parts = [
            title,
            (getattr(article, 'summary', '') or "").lower(),
        ]
        content = (getattr(article, 'content', '') or "").lower()
        if content and len(content) < 2000:
            text_parts.append(content)
        
        searchable_text = " ".join(text_parts)
        
        if not searchable_text or len(searchable_text) < 10:
            return False
        
        # Need 2+ UNIQUE non-ambiguous keywords, or 3+ including ambiguous
        matches = self._tech_pattern.findall(searchable_text)
        unique_keywords = set(m.lower() for m in matches)
        non_ambiguous = unique_keywords - AMBIGUOUS_KEYWORDS
        
        if len(non_ambiguous) >= 2:
            return True
        if len(unique_keywords) >= 3:
            return True
        
        return False

    def _check_quality(self, article: Article) -> str:
        """
        Perform heuristic checks for content quality.
        
        Returns:
            "ok" — passes quality checks
            "spam" — detected as spam
            "low_quality" — too short, generic, or empty
        """
        title = (article.title or "").strip()
        
        # Reject very short titles
        if len(title) < 10:
            return "low_quality"
        
        title_lower = title.lower()
        
        # Reject generic navigation titles
        if title_lower in self._generic_titles:
            return "low_quality"
        
        # CRITICAL: Reject titles with fewer than 4 words — these are
        # section headings / nav links ("Programming", "Open Source",
        # "Memory and Storage", "Solar System"), not real headlines.
        words = [w for w in title.split() if len(w) > 1]  # ignore single-char "words"
        if len(words) < 4:
            return "low_quality"
        
        # Reject titles that are ALL CAPS with very few words (clickbait)
        if len(words) < 5 and title == title.upper() and len(title) > 5:
            return "low_quality"

        # Reject titles that start with brackets (site names like "[Annals of Internal Medicine]")
        if title.startswith("[") or title.startswith("{"):
            return "low_quality"

        # Reject garbled HTML concatenation (no spaces between words, very long single "word")
        longest_word = max((w for w in title.split()), key=len, default="")
        if len(longest_word) > 40:
            return "low_quality"

        # Reject titles that look like navigation ("View more", "Read more", "See all")
        nav_prefixes = ("view more", "read more", "see all", "see more", "load more", "show more", "view all")
        if any(title_lower.startswith(p) for p in nav_prefixes):
            return "low_quality"
        
        # Check for spam patterns in title + summary using pre-compiled regex
        summary = getattr(article, 'summary', '') or ""
        combined = f"{title_lower} {summary.lower()}"
        
        if self._spam_pattern.search(combined):
            return "spam"
        
        return "ok"

    def check_publishable(self, article: Article) -> tuple:
        """
        Check if an article is ready for Telegram publishing.
        Enforces the HARD requirement: no publish without thumbnail + summary.
        
        Returns:
            (bool, str) — (is_publishable, reason_if_not)
        """
        title = (article.title or "").strip()
        summary = (getattr(article, 'summary', '') or "").strip()
        image_url = getattr(article, 'image_url', None) or getattr(article, 'thumbnail_url', None)
        url = (article.url or "").strip()

        if not title or len(title) < 15:
            return False, "no_title"
        if not url:
            return False, "no_url"
        if not summary or len(summary) < 20:
            return False, "no_summary"
        if not image_url:
            return False, "no_thumbnail"
        
        return True, "ok"

    def update_source_score(self, source_url: str, success: bool):
        """Update reliability score for a source."""
        # Simple moving average-like update
        current = self._source_reliability.get(source_url, 1.0)
        if success:
            new_score = min(1.0, current + 0.05)
        else:
            new_score = max(0.0, current - 0.2)  # Penalty is harsher
            
        self._source_reliability[source_url] = new_score
