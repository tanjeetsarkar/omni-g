package ingest

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestExtractProvenance_DocumentTitleAndURL(t *testing.T) {
	block := `{"document_title":"PubMed Central Article","source_url":"https://pubmed.ncbi.nlm.nih.gov/12345","text":"some body"}`
	p := ExtractProvenance(block)
	assert.Equal(t, "PubMed Central Article", p.SourceName)
	assert.Equal(t, "https://pubmed.ncbi.nlm.nih.gov/12345", p.SourceURL)
}

func TestExtractProvenance_PublisherNameFallback(t *testing.T) {
	block := `{"publisher_name":"Reuters","url":"https://reuters.com/article/1","content":"body"}`
	p := ExtractProvenance(block)
	assert.Equal(t, "Reuters", p.SourceName)
	assert.Equal(t, "https://reuters.com/article/1", p.SourceURL)
}

func TestExtractProvenance_HeadlineKey(t *testing.T) {
	block := `{"headline":"Breaking News","text":"body"}`
	p := ExtractProvenance(block)
	assert.Equal(t, "Breaking News", p.SourceName)
	assert.Equal(t, "", p.SourceURL)
}

func TestExtractProvenance_CaseInsensitiveKeys(t *testing.T) {
	block := `{"Title":"Mixed Case Title","URL":"https://example.com"}`
	p := ExtractProvenance(block)
	assert.Equal(t, "Mixed Case Title", p.SourceName)
	assert.Equal(t, "https://example.com", p.SourceURL)
}

func TestExtractProvenance_MalformedJSONReturnsEmpty(t *testing.T) {
	p := ExtractProvenance("not json {{")
	assert.Equal(t, Provenance{}, p)
}

func TestExtractProvenance_NoCandidateKeysReturnsEmpty(t *testing.T) {
	block := `{"text":"just body content","unrelated":"field"}`
	p := ExtractProvenance(block)
	assert.Equal(t, Provenance{}, p)
}

func TestExtractProvenance_EmptyStringValueSkipped(t *testing.T) {
	block := `{"title":"","headline":"Real Headline","text":"body"}`
	p := ExtractProvenance(block)
	assert.Equal(t, "Real Headline", p.SourceName)
}

func TestExtractProvenance_DocumentTitlePreferredOverTitle(t *testing.T) {
	// document_title is listed before title in sourceNameKeys, so it wins.
	block := `{"document_title":"Primary","title":"Secondary","text":"body"}`
	p := ExtractProvenance(block)
	assert.Equal(t, "Primary", p.SourceName)
}
