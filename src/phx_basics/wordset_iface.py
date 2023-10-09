from abc import abstractmethod, ABC


class WordsetInterface(ABC):
    @abstractmethod
    def get_words(self):
        """
        @return set of words in this object
        """
        raise RuntimeError("Unimplemented method get_words() of abstract interface WordsetInterface")

    @abstractmethod
    def get_graphemes(self):
        """
        @return set of graphemes in this object
        """
        raise RuntimeError("Unimplemented method get_graphemes() of abstract interface WordsetInterface")