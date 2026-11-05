{# Where an external model is written: <data dir>/<layer>/<model>.parquet #}
{% macro layer_location(layer, name=none) %}
  {{- env_var('OSS_PULSE_DATA_DIR') ~ '/' ~ layer ~ '/' ~ (name or this.name) ~ '.parquet' -}}
{% endmacro %}

{# Custom schemas are used as given, without the target schema as a prefix. #}
{% macro generate_schema_name(custom_schema_name, node) %}
  {{- custom_schema_name or target.schema -}}
{% endmacro %}
