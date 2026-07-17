"""
Speeky - A self-hosted, offline, AI-assisted English language practice pipeline.

This package provides modules for speech recognition, pronunciation analysis,
grammar correction, fluency assessment, and conversational practice using
British English standards.
"""

__version__ = "0.1.0"
__author__ = "Speeky Project"

from .vad import VoiceActivityDetector
from .asr import AutomaticSpeechRecognition
from .alignment import WordAligner
from .pronunciation import PronunciationScorer
from .grammar import GrammarCorrector
from .fluency import FluencyAnalyzer
from .response import ConversationEngine
from .tts import TextToSpeech
from .pipeline import SpeekyPipeline

__all__ = [
    "VoiceActivityDetector",
    "AutomaticSpeechRecognition", 
    "WordAligner",
    "PronunciationScorer",
    "GrammarCorrector",
    "FluencyAnalyzer",
    "ConversationEngine",
    "TextToSpeech",
    "SpeekyPipeline",
]
