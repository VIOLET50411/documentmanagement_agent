from app.ingestion.metadata.tagger import MetadataTagger


def test_metadata_tagger_replaces_temp_section_title_with_document_title():
    tagger = MetadataTagger()

    chunks = [
        {
            "content": "国有资产管理相关内容",
            "section_title": "tmpujzfainw",
        }
    ]

    tagged = tagger.tag(
        chunks,
        {
            "title": "西南大学国有资产管理办法（修订）.pdf",
            "file_name": "tmp_upload_name.pdf",
            "tenant_id": "default",
        },
    )

    assert tagged[0]["section_title"] == "西南大学国有资产管理办法（修订）.pdf"


def test_metadata_tagger_keeps_real_section_title():
    tagger = MetadataTagger()

    chunks = [
        {
            "content": "固定资产配置和管理要求",
            "section_title": "第二章 管理机构和职责分工",
        }
    ]

    tagged = tagger.tag(
        chunks,
        {
            "title": "西南大学固定资产管理办法.pdf",
            "tenant_id": "default",
        },
    )

    assert tagged[0]["section_title"] == "第二章 管理机构和职责分工"
