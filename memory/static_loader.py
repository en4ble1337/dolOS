import logging
import os
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class StaticFileLoader:
    """Chunks static Markdown files and indexes them into semantic memory.

    Skips files that are already indexed and unchanged (checks by source_tag + mtime).
    Call index_file() at agent startup for USER.md and MEMORY.md.
    """

    def __init__(
        self,
        memory: "MemoryManager",
        chunk_size: int = 400,
        overlap: int = 80,
    ) -> None:
        """Initialize the StaticFileLoader.

        Args:
            memory: MemoryManager instance used for storing and searching chunks.
            chunk_size: Maximum characters per chunk.
            overlap: Number of characters from the end of the previous chunk to
                     prepend to the start of the next chunk.
        """
        self.memory = memory
        self.chunk_size = chunk_size
        self.overlap = overlap

    def index_file(self, path: str, source_tag: str) -> int:
        """Chunk a Markdown file and upsert chunks into semantic memory.

        - Skips if file not found (logs warning, returns 0).
        - Skips if file mtime matches last indexed mtime (already up to date).
        - Stores each chunk with metadata: source=source_tag, chunk_index=N,
          mtime=float, path=path
        - importance=0.6 for all static file chunks
        - Returns count of chunks stored.

        Args:
            path: Absolute or relative path to the Markdown file.
            source_tag: Tag stored in the ``source`` metadata field, used to
                        identify and look up chunks for this file.

        Returns:
            Number of chunks stored (0 if skipped or file missing).
        """
        if not os.path.isfile(path):
            logger.warning("StaticFileLoader: file not found, skipping: %s", path)
            return 0

        current_mtime: float = os.path.getmtime(path)

        stored_mtime = self._get_stored_mtime(source_tag)
        if stored_mtime is not None and stored_mtime == current_mtime:
            logger.debug(
                "StaticFileLoader: '%s' is up to date (mtime=%.3f), skipping.",
                source_tag,
                current_mtime,
            )
            return 0

        if stored_mtime is not None and stored_mtime != current_mtime:
            logger.warning(
                "StaticFileLoader: mtime changed for source_tag='%s' "
                "(old=%.3f, new=%.3f). Old chunks will persist until evicted.",
                source_tag,
                stored_mtime,
                current_mtime,
            )

        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()

        chunks = self._chunk_text(text)
        if not chunks:
            logger.debug("StaticFileLoader: no chunks produced for '%s'.", path)
            return 0

        for index, chunk in enumerate(chunks):
            metadata = {
                "source": source_tag,
                "chunk_index": index,
                "mtime": current_mtime,
                "path": path,
            }
            self.memory.add_memory(
                text=chunk,
                memory_type="semantic",
                importance=0.6,
                metadata=metadata,
            )

        logger.info(
            "StaticFileLoader: indexed %d chunks from '%s' (source_tag='%s').",
            len(chunks),
            path,
            source_tag,
        )
        return len(chunks)

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping character windows, respecting paragraph breaks.

        Strategy:
        1. Split on double newlines to get paragraphs.
        2. If a paragraph exceeds chunk_size, split it further by characters.
        3. Reassemble with overlap: prepend the last ``overlap`` chars of the
           previous chunk to the start of the next chunk.
        4. Strip empty chunks.

        Args:
            text: Full document text.

        Returns:
            List of non-empty chunk strings.
        """
        if not text.strip():
            return []

        # Step 1 & 2: collect raw segments respecting chunk_size
        raw_segments: List[str] = []
        paragraphs = text.split("\n\n")

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(para) <= self.chunk_size:
                raw_segments.append(para)
            else:
                # Character-split large paragraphs
                start = 0
                while start < len(para):
                    raw_segments.append(para[start : start + self.chunk_size])
                    start += self.chunk_size

        if not raw_segments:
            return []

        # Step 3: reassemble with overlap between consecutive segments
        chunks: List[str] = []
        for i, segment in enumerate(raw_segments):
            if i == 0:
                chunks.append(segment)
            else:
                prev_chunk = chunks[-1]
                overlap_prefix = prev_chunk[-self.overlap :] if len(prev_chunk) >= self.overlap else prev_chunk
                chunks.append(overlap_prefix + segment)

        # Step 4: strip and drop empties
        return [c.strip() for c in chunks if c.strip()]

    def _get_stored_mtime(self, source_tag: str) -> Optional[float]:
        """Search semantic memory for any chunk with this source_tag, return its stored mtime.

        Args:
            source_tag: The ``source`` metadata value to filter by.

        Returns:
            The stored mtime float if found, otherwise None.
        """
        try:
            results = self.memory.search(
                query=source_tag,
                memory_type="semantic",
                filter_metadata={"source": source_tag},
                limit=1,
            )
        except Exception as exc:
            logger.warning(
                "StaticFileLoader: error searching for stored mtime of '%s': %s",
                source_tag,
                exc,
            )
            return None

        if not results:
            return None

        mtime = results[0].get("metadata", {}).get("mtime")
        if mtime is None:
            return None
        try:
            return float(mtime)
        except (TypeError, ValueError):
            return None
