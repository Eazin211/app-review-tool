from typing import Optional


class TraceabilityValidator:
    def __init__(self):
        pass

    def validate_pipeline(
        self,
        reviews: list[dict],
        cleaned_reviews: list[dict],
        analysis: dict,
        prd: dict,
        test_results: dict,
        progress_callback=None
    ) -> dict:
        if progress_callback:
            progress_callback('Validating traceability chain...')

        results = {
            'valid': True,
            'issues': [],
            'warnings': [],
            'stats': {},
            'traceability_matrix': self._build_traceability_matrix(
                cleaned_reviews, analysis, prd, test_results
            )
        }

        self._validate_review_to_finding(cleaned_reviews, analysis, results)
        self._validate_finding_to_requirement(analysis, prd, results)
        self._validate_requirement_to_test(prd, test_results, results)
        self._validate_full_chain(cleaned_reviews, analysis, prd, test_results, results)
        self._check_unsupported_claims(analysis, results)

        results['stats'] = {
            'total_reviews': len(cleaned_reviews),
            'total_findings': len(analysis.get('findings', [])),
            'total_requirements': len(prd.get('requirements', [])),
            'total_test_cases': test_results.get('total_test_cases', 0),
            'issues_found': len(results['issues']),
            'warnings_found': len(results['warnings']),
            'validation_passed': len(results['issues']) == 0
        }

        results['valid'] = len(results['issues']) == 0

        return results

    def _validate_review_to_finding(
        self,
        reviews: list[dict],
        analysis: dict,
        results: dict
    ):
        review_ids = {r.get('review_id', '') for r in reviews}
        findings = analysis.get('findings', [])

        finding_review_ids = set()
        for finding in findings:
            for rid in finding.get('source_review_ids', []):
                finding_review_ids.add(rid)

        orphan_review_ids = review_ids - finding_review_ids
        if orphan_review_ids:
            results['warnings'].append({
                'level': 'warning',
                'stage': 'review_to_finding',
                'message': f'{len(orphan_review_ids)} reviews are not referenced in any finding',
                'affected_ids': list(orphan_review_ids)[:10]
            })

        for finding in findings:
            source_ids = finding.get('source_review_ids', [])
            invalid_ids = [rid for rid in source_ids if rid not in review_ids]
            if invalid_ids:
                results['issues'].append({
                    'level': 'error',
                    'stage': 'review_to_finding',
                    'message': f'Finding "{finding.get("label", "")}" references {len(invalid_ids)} non-existent review IDs',
                    'finding_label': finding.get('label', '')
                })

    def _validate_finding_to_requirement(
        self,
        analysis: dict,
        prd: dict,
        results: dict
    ):
        findings = analysis.get('findings', [])
        requirements = prd.get('requirements', [])

        finding_labels = {f.get('label', '') for f in findings}

        for req in requirements:
            source_findings = req.get('source_findings', [])
            for sf in source_findings:
                if sf not in finding_labels:
                    results['warnings'].append({
                        'level': 'warning',
                        'stage': 'finding_to_requirement',
                        'message': f'Requirement {req.get("id", "")} references non-existent finding "{sf}"'
                    })

        requirement_finding_labels = set()
        for req in requirements:
            for sf in req.get('source_findings', []):
                requirement_finding_labels.add(sf)

        orphan_findings = finding_labels - requirement_finding_labels
        if orphan_findings:
            results['warnings'].append({
                'level': 'warning',
                'stage': 'finding_to_requirement',
                'message': f'{len(orphan_findings)} findings are not referenced in any requirement',
                'affected_labels': list(orphan_findings)[:10]
            })

    def _validate_requirement_to_test(
        self,
        prd: dict,
        test_results: dict,
        results: dict
    ):
        requirements = prd.get('requirements', [])
        test_cases = test_results.get('test_cases', [])

        req_ids = {r.get('id', '') for r in requirements}
        tc_req_ids = set()
        for tc in test_cases:
            tc_req_ids.add(tc.get('requirement_id', ''))

        uncovered = req_ids - tc_req_ids
        if uncovered:
            results['issues'].append({
                'level': 'error',
                'stage': 'requirement_to_test',
                'message': f'{len(uncovered)} requirements have no test cases',
                'affected_ids': list(uncovered)
            })

        invalid_refs = tc_req_ids - req_ids
        if invalid_refs:
            results['issues'].append({
                'level': 'error',
                'stage': 'requirement_to_test',
                'message': f'{len(invalid_refs)} test cases reference non-existent requirements',
                'affected_ids': list(invalid_refs)
            })

    def _validate_full_chain(
        self,
        reviews: list[dict],
        analysis: dict,
        prd: dict,
        test_results: dict,
        results: dict
    ):
        review_ids = {r.get('review_id', '') for r in reviews}
        findings = analysis.get('findings', [])
        requirements = prd.get('requirements', [])
        test_cases = test_results.get('test_cases', [])

        for tc in test_cases:
            req_id = tc.get('requirement_id', '')
            source_reviews_tc = set(tc.get('source_review_ids', []))

            req = None
            for r in requirements:
                if r.get('id') == req_id:
                    req = r
                    break

            if req:
                req_reviews = set(req.get('source_review_ids', []))
                for src_rid in source_reviews_tc:
                    if src_rid not in req_reviews:
                        results['warnings'].append({
                            'level': 'warning',
                            'stage': 'full_chain',
                            'message': f'Test case {tc.get("id", "")} references review {src_rid} not in requirement {req_id}'
                        })

        for finding in findings:
            finding_review_ids = set(finding.get('source_review_ids', []))
            finding_label = finding.get('label', '')

            linked_reqs = [r for r in requirements if finding_label in r.get('source_findings', [])]

            if not linked_reqs and finding.get('type') != 'positive_feedback':
                results['warnings'].append({
                    'level': 'warning',
                    'stage': 'full_chain',
                    'message': f'Finding "{finding_label}" has no linked requirements (except positive feedback)'
                })

    def _check_unsupported_claims(self, analysis: dict, results: dict):
        findings = analysis.get('findings', [])

        for finding in findings:
            support_count = finding.get('support_count', 0)
            confidence = finding.get('confidence', 0)
            source_ids = finding.get('source_review_ids', [])

            if support_count == 0 and finding.get('type') != 'positive_feedback':
                results['issues'].append({
                    'level': 'error',
                    'stage': 'validation',
                    'message': f'Finding "{finding.get("label", "")}" has zero supporting reviews',
                    'finding_label': finding.get('label', '')
                })

            if support_count < 2 and finding.get('severity') in ('high',):
                results['warnings'].append({
                    'level': 'warning',
                    'stage': 'validation',
                    'message': f'High-severity finding "{finding.get("label", "")}" has only {support_count} supporting reviews',
                    'finding_label': finding.get('label', '')
                })

    def _build_traceability_matrix(
        self,
        reviews: list[dict],
        analysis: dict,
        prd: dict,
        test_results: dict
    ) -> list[dict]:
        matrix = []
        findings = analysis.get('findings', [])
        requirements = prd.get('requirements', [])
        test_cases = test_results.get('test_cases', [])

        for review in reviews[:50]:
            rid = review.get('review_id', '')
            row = {
                'review_id': rid,
                'rating': review.get('rating', 0),
                'review_excerpt': (review.get('content', '') or review.get('title', ''))[:100],
                'findings': [],
                'requirements': [],
                'test_cases': []
            }

            for finding in findings:
                if rid in finding.get('source_review_ids', []):
                    row['findings'].append(finding.get('label', ''))

            for req in requirements:
                if rid in req.get('source_review_ids', []):
                    row['requirements'].append(req.get('id', ''))

            for tc in test_cases:
                if rid in tc.get('source_review_ids', []):
                    row['test_cases'].append(tc.get('id', ''))

            if row['findings'] or row['requirements'] or row['test_cases']:
                matrix.append(row)

        return matrix
