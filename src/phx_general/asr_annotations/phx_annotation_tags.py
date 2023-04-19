from typing import Iterable


class PhxAnnotationTags:
    """
    Allowed tags for PhxAnnotation class and child classes (PhxStm, PhxStmKws).
    Moved to separate class to avoid circular dependency problems
 
    WARNING:
    duplicate with class PhxAnnotationTags_Standalone in script:
    general/documentation/stt_scoring_on_site/prepare_scoring_stm.py
    If anything gets changed here, consider changing it there as well
    """
    SILENCE_TAGS = {'<sil>'}
    NONSILENCE_TAGS = {'<unk>', '<hes>'}
    ALL = NONSILENCE_TAGS.union(SILENCE_TAGS)

    @classmethod
    def delete_tags_from_string(cls, string: str, delimiter=" "):
        return delimiter.join(cls.delete_tags_from_iterable(string.split()))

    @classmethod
    def delete_tags_from_iterable(cls, iterable: Iterable):
        """
        Return list without any tag
        """
        return [word for word in iterable if word not in cls.ALL]
