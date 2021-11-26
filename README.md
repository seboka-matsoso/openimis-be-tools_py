# openIMIS Backend Report reference module
This repository holds the files of the openIMIS Backend Core reference module.
It is a required module of [openimis-be_py](https://github.com/openimis/openimis-be_py).

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

## ORM mapping:
* report_ReportDefinition > ReportDefinition

## Listened Django Signals
None

## Services
* ReportService: process (ReportBro engine) named report

## Reports (template can be overloaded via report.ReportDefinition)
None

## GraphQL Queries
None

## GraphQL Mutations - each mutation emits default signals and return standard error lists (cfr. openimis-be-core_py)
None

## Configuration options (can be changed via core.ModuleConfiguration)
None

## openIMIS Modules Dependencies
* core.models.UUIDModel