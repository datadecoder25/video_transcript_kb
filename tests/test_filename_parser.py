from transcripts.filename_parser import parse_filename


def test_standard_client_and_topic():
    result = parse_filename("22_Ventures_Vaginal_Probiotics_Analysis_transcribed.json")
    assert result == {
        "client": "22 Ventures",
        "topic": "Vaginal Probiotics Analysis",
        "stem": "22_Ventures_Vaginal_Probiotics_Analysis",
    }


def test_no_client_topic_only():
    result = parse_filename("Ad_launch____4_Product_targeting_campaign_transcribed.json")
    assert result["client"] == ""
    assert result["topic"] != ""
    assert "_transcribed" not in result["stem"]


def test_missing_transcribed_suffix():
    result = parse_filename("AMC_Use_Case___LTV_V2.json")
    assert result["stem"] == "AMC_Use_Case___LTV_V2"
    assert result["client"] == "AMC"
    assert "LTV" in result["topic"]


def test_no_json_extension():
    result = parse_filename("AMC_Use_Case___LTV_transcribed")
    assert result["stem"] == "AMC_Use_Case___LTV"


def test_single_word_filename():
    result = parse_filename("Onboarding_transcribed.json")
    assert result["client"] == ""
    assert result["topic"] != ""
    assert result["stem"] == "Onboarding"


def test_all_topic_words():
    result = parse_filename("Ad_program_file_improvement__1_transcribed.json")
    assert result["client"] == ""
    assert "Ad" in result["topic"]


def test_double_underscores_handled():
    result = parse_filename("AI_Tool_combining_SQP__time_series___SP_Imp_Share__Top_Search_Terms_report_transcribed.json")
    assert result["client"] == "AI"
    assert "Tool" in result["topic"]
    assert result["stem"] == "AI_Tool_combining_SQP__time_series___SP_Imp_Share__Top_Search_Terms_report"


def test_path_prefix_stripped():
    result = parse_filename("/some/path/to/22_Ventures_Vaginal_Probiotics_Analysis_transcribed.json")
    assert result["client"] == "22 Ventures"
    assert result["topic"] == "Vaginal Probiotics Analysis"
