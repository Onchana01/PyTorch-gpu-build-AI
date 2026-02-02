from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone

from src.common.dto.test_result import TestCase, TestSuite, TestReport, TestStatus
from src.common.config.logging_config import get_logger
from src.common.exceptions.build_exceptions import TestFailedException


logger = get_logger(__name__)


class TestFramework(str, Enum):
    PYTEST = "pytest"
    GTEST = "gtest"
    CTEST = "ctest"
    UNITTEST = "unittest"


@dataclass
class TestConfig:
    framework: TestFramework = TestFramework.PYTEST
    test_paths: List[str] = field(default_factory=list)
    filter_pattern: Optional[str] = None
    exclude_pattern: Optional[str] = None
    parallel_workers: int = 1
    timeout_seconds: int = 3600
    extra_args: List[str] = field(default_factory=list)
    env_vars: Dict[str, str] = field(default_factory=dict)
    collect_coverage: bool = False
    xml_output_path: Optional[str] = None


@dataclass
class TestExecutionResult:
    success: bool
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    test_suites: List[TestSuite] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    xml_report_path: Optional[str] = None
    coverage_report_path: Optional[str] = None


class TestRunner:
    def __init__(
        self,
        config: Optional[TestConfig] = None,
        working_dir: Optional[str] = None,
    ):
        self._config = config or TestConfig()
        self._working_dir = working_dir or os.getcwd()
        self._env = self._setup_environment()
    
    def _setup_environment(self) -> Dict[str, str]:
        env = os.environ.copy()
        
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTEST_ADDOPTS"] = "--tb=short"
        
        env.update(self._config.env_vars)
        
        return env
    
    async def run_tests(
        self,
        test_paths: Optional[List[str]] = None,
    ) -> TestExecutionResult:
        paths = test_paths or self._config.test_paths
        
        if self._config.framework == TestFramework.PYTEST:
            return await self._run_pytest(paths)
        elif self._config.framework == TestFramework.GTEST:
            return await self._run_gtest(paths)
        elif self._config.framework == TestFramework.CTEST:
            return await self._run_ctest()
        elif self._config.framework == TestFramework.UNITTEST:
            return await self._run_unittest(paths)
        else:
            raise ValueError(f"Unsupported test framework: {self._config.framework}")
    
    async def _run_pytest(self, test_paths: List[str]) -> TestExecutionResult:
        xml_output = self._config.xml_output_path or f"{self._working_dir}/test-results.xml"
        
        cmd = ["python", "-m", "pytest"]
        cmd.extend(test_paths)
        cmd.extend(["--junitxml", xml_output])
        cmd.extend([f"-n{self._config.parallel_workers}" if self._config.parallel_workers > 1 else ""])
        cmd.append("-v")
        
        if self._config.filter_pattern:
            cmd.extend(["-k", self._config.filter_pattern])
        
        if self._config.collect_coverage:
            cmd.extend(["--cov", "--cov-report=xml"])
        
        cmd.extend(self._config.extra_args)
        
        cmd = [c for c in cmd if c]
        
        logger.info(f"Running pytest: {' '.join(cmd)}")
        
        return await self._execute_test_command(cmd, xml_output)
    
    async def _run_gtest(self, test_paths: List[str]) -> TestExecutionResult:
        xml_output = self._config.xml_output_path or f"{self._working_dir}/test-results.xml"
        
        all_results = TestExecutionResult(success=True)
        
        for test_binary in test_paths:
            cmd = [test_binary, f"--gtest_output=xml:{xml_output}"]
            
            if self._config.filter_pattern:
                cmd.append(f"--gtest_filter={self._config.filter_pattern}")
            
            result = await self._execute_test_command(cmd, xml_output)
            
            all_results.total_tests += result.total_tests
            all_results.passed += result.passed
            all_results.failed += result.failed
            all_results.skipped += result.skipped
            all_results.errors += result.errors
            all_results.duration_seconds += result.duration_seconds
            all_results.test_suites.extend(result.test_suites)
            
            if not result.success:
                all_results.success = False
        
        return all_results
    
    async def _run_ctest(self) -> TestExecutionResult:
        xml_output = self._config.xml_output_path or f"{self._working_dir}/test-results.xml"
        
        cmd = [
            "ctest",
            "--output-on-failure",
            f"--parallel={self._config.parallel_workers}",
            f"--output-junit={xml_output}",
        ]
        
        if self._config.filter_pattern:
            cmd.extend(["-R", self._config.filter_pattern])
        
        if self._config.exclude_pattern:
            cmd.extend(["-E", self._config.exclude_pattern])
        
        cmd.extend(self._config.extra_args)
        
        logger.info(f"Running ctest: {' '.join(cmd)}")
        
        return await self._execute_test_command(cmd, xml_output)
    
    async def _run_unittest(self, test_paths: List[str]) -> TestExecutionResult:
        xml_output = self._config.xml_output_path or f"{self._working_dir}/test-results.xml"
        
        cmd = ["python", "-m", "xmlrunner"]
        cmd.extend(test_paths)
        cmd.extend(["-o", os.path.dirname(xml_output)])
        
        logger.info(f"Running unittest: {' '.join(cmd)}")
        
        return await self._execute_test_command(cmd, xml_output)
    
    async def _execute_test_command(
        self,
        cmd: List[str],
        xml_output: str,
    ) -> TestExecutionResult:
        start_time = datetime.now(timezone.utc)
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self._working_dir,
                env=self._env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self._config.timeout_seconds
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise TestFailedException(
                    message=f"Test execution timed out after {self._config.timeout_seconds}s",
                    test_suite="all",
                    failed_tests=["timeout"],
                )
            
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")
            
            result = self._parse_xml_results(xml_output)
            result.stdout = stdout_str
            result.stderr = stderr_str
            result.duration_seconds = duration
            result.xml_report_path = xml_output
            result.success = process.returncode == 0
            
            if not result.success:
                logger.warning(f"Tests completed with failures: {result.failed} failed, {result.passed} passed")
            else:
                logger.info(f"All {result.total_tests} tests passed in {duration:.2f}s")
            
            return result
            
        except TestFailedException:
            raise
        except Exception as e:
            logger.exception(f"Test execution error: {e}")
            return TestExecutionResult(
                success=False,
                stderr=str(e),
            )
    
    def _parse_xml_results(self, xml_path: str) -> TestExecutionResult:
        result = TestExecutionResult(success=True)
        
        if not Path(xml_path).exists():
            logger.warning(f"XML results file not found: {xml_path}")
            return result
        
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            
            if root.tag == "testsuites":
                for suite_elem in root.findall("testsuite"):
                    suite = self._parse_test_suite(suite_elem)
                    result.test_suites.append(suite)
            elif root.tag == "testsuite":
                suite = self._parse_test_suite(root)
                result.test_suites.append(suite)
            
            for suite in result.test_suites:
                result.total_tests += len(suite.test_cases)
                for test in suite.test_cases:
                    if test.status == TestStatus.PASSED:
                        result.passed += 1
                    elif test.status == TestStatus.FAILED:
                        result.failed += 1
                    elif test.status == TestStatus.SKIPPED:
                        result.skipped += 1
                    elif test.status == TestStatus.ERROR:
                        result.errors += 1
            
            result.success = result.failed == 0 and result.errors == 0
            
        except Exception as e:
            logger.warning(f"Failed to parse XML results: {e}")
        
        return result
    
    def _parse_test_suite(self, suite_elem: ET.Element) -> TestSuite:
        test_cases: List[TestCase] = []
        
        for case_elem in suite_elem.findall("testcase"):
            status = TestStatus.PASSED
            error_message = None
            
            failure = case_elem.find("failure")
            if failure is not None:
                status = TestStatus.FAILED
                error_message = failure.get("message", failure.text)
            
            error = case_elem.find("error")
            if error is not None:
                status = TestStatus.ERROR
                error_message = error.get("message", error.text)
            
            skipped = case_elem.find("skipped")
            if skipped is not None:
                status = TestStatus.SKIPPED
                error_message = skipped.get("message", skipped.text)
            
            time_str = case_elem.get("time", "0")
            try:
                duration = float(time_str)
            except ValueError:
                duration = 0.0
            
            test_case = TestCase(
                name=case_elem.get("name", "unknown"),
                class_name=case_elem.get("classname", ""),
                status=status,
                duration_seconds=duration,
                error_message=error_message,
            )
            test_cases.append(test_case)
        
        time_str = suite_elem.get("time", "0")
        try:
            suite_time = float(time_str)
        except ValueError:
            suite_time = 0.0
        
        return TestSuite(
            name=suite_elem.get("name", "unknown"),
            test_cases=test_cases,
            duration_seconds=suite_time,
        )
    
    async def discover_tests(
        self,
        search_paths: Optional[List[str]] = None,
    ) -> List[str]:
        paths = search_paths or self._config.test_paths
        discovered: List[str] = []
        
        if self._config.framework == TestFramework.PYTEST:
            cmd = ["python", "-m", "pytest", "--collect-only", "-q"]
            cmd.extend(paths)
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self._working_dir,
                env=self._env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, _ = await process.communicate()
            output = stdout.decode("utf-8", errors="replace")
            
            for line in output.split("\n"):
                if "::" in line and not line.startswith(" "):
                    discovered.append(line.strip())
        
        elif self._config.framework == TestFramework.CTEST:
            cmd = ["ctest", "-N"]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self._working_dir,
                env=self._env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, _ = await process.communicate()
            output = stdout.decode("utf-8", errors="replace")
            
            for line in output.split("\n"):
                match = re.match(r"\s*Test\s+#\d+:\s+(\S+)", line)
                if match:
                    discovered.append(match.group(1))
        
        return discovered
    
    def set_config(self, config: TestConfig) -> None:
        self._config = config
        self._env = self._setup_environment()
