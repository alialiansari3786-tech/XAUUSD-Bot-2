"""
Claude Vision API Integration
Analyzes trading chart screenshots for pattern learning and validation
"""

import os
import base64
import json
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from src.utils.logger import setup_logger
from config.settings import settings


logger = setup_logger(__name__, settings.LOG_LEVEL)


class ClaudeVisionAnalyzer:
    """
    Claude Vision API integration for chart screenshot analysis

    Capabilities:
    - Pattern recognition from chart images
    - Trade setup validation
    - Structure identification from screenshots
    - Educational feedback on chart analysis
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Claude Vision analyzer

        Args:
            api_key: Anthropic API key (defaults to settings.CLAUDE_API_KEY)
        """
        if not ANTHROPIC_AVAILABLE:
            logger.warning("Anthropic package not installed. Claude Vision features disabled.")
            self.client = None
            return

        self.api_key = api_key or settings.CLAUDE_API_KEY

        if not self.api_key or self.api_key == 'your_claude_api_key_here':
            logger.warning("Claude API key not configured. Vision analysis disabled.")
            self.client = None
        else:
            try:
                self.client = Anthropic(api_key=self.api_key)
                logger.info("Claude Vision analyzer initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Claude client: {e}")
                self.client = None

    def is_available(self) -> bool:
        """Check if Claude Vision is available"""
        return self.client is not None

    def analyze_chart_screenshot(
        self,
        image_path: str,
        analysis_type: str = 'general',
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Analyze a trading chart screenshot using Claude Vision

        Args:
            image_path: Path to chart image file
            analysis_type: Type of analysis - 'general', 'pattern', 'setup', 'structure'
            context: Optional context (timeframe, method, detected levels, etc.)

        Returns:
            Dictionary containing analysis results
        """
        if not self.is_available():
            return {
                'success': False,
                'error': 'Claude Vision not available',
                'message': 'API key not configured or anthropic package not installed'
            }

        try:
            # Read and encode image
            image_data = self._load_image(image_path)
            if not image_data:
                return {
                    'success': False,
                    'error': 'Failed to load image',
                    'image_path': image_path
                }

            # Build prompt based on analysis type
            prompt = self._build_analysis_prompt(analysis_type, context)

            # Call Claude Vision API
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",  # Claude 3.5 Sonnet with vision
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": image_data['media_type'],
                                    "data": image_data['base64']
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )

            # Parse response
            analysis_text = response.content[0].text

            result = {
                'success': True,
                'analysis': analysis_text,
                'analysis_type': analysis_type,
                'image_path': image_path,
                'timestamp': datetime.now().isoformat(),
                'model': response.model,
                'usage': {
                    'input_tokens': response.usage.input_tokens,
                    'output_tokens': response.usage.output_tokens
                }
            }

            # Add context if provided
            if context:
                result['context'] = context

            logger.info(f"Chart analysis completed: {analysis_type}")
            return result

        except Exception as e:
            logger.error(f"Claude Vision analysis failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'image_path': image_path,
                'analysis_type': analysis_type
            }

    def validate_trade_setup(
        self,
        image_path: str,
        trade_details: Dict
    ) -> Dict[str, Any]:
        """
        Validate a trade setup from chart screenshot

        Args:
            image_path: Path to chart image
            trade_details: Dictionary with entry, SL, TP, bias, method, etc.

        Returns:
            Validation results with suggestions
        """
        context = {
            'trade_details': trade_details,
            'validation_mode': True
        }

        prompt_additions = f"""

Trade Setup to Validate:
- Direction: {trade_details.get('bias', 'N/A')}
- Entry: {trade_details.get('entry', 'N/A')}
- Stop Loss: {trade_details.get('sl', 'N/A')}
- Take Profit: {trade_details.get('tp', 'N/A')}
- Method: {trade_details.get('method', 'N/A')}
- Confluence Score: {trade_details.get('confluence', 'N/A')}

Please validate this setup against the chart and provide:
1. Is the setup valid based on the chart?
2. Are entry, SL, and TP levels appropriate?
3. Any risks or concerns?
4. Suggestions for improvement
5. Overall confidence (Low/Medium/High)
"""

        result = self.analyze_chart_screenshot(
            image_path,
            analysis_type='setup',
            context=context
        )

        if result['success']:
            result['prompt_additions'] = prompt_additions

        return result

    def identify_patterns(
        self,
        image_path: str,
        timeframe: str = 'M15'
    ) -> Dict[str, Any]:
        """
        Identify trading patterns from chart screenshot

        Args:
            image_path: Path to chart image
            timeframe: Chart timeframe

        Returns:
            Dictionary with identified patterns
        """
        context = {
            'timeframe': timeframe,
            'pattern_detection': True
        }

        return self.analyze_chart_screenshot(
            image_path,
            analysis_type='pattern',
            context=context
        )

    def learn_from_outcome(
        self,
        setup_image_path: str,
        outcome_image_path: str,
        trade_result: Dict
    ) -> Dict[str, Any]:
        """
        Learn from trade outcome by comparing setup vs result

        Args:
            setup_image_path: Chart at trade entry
            outcome_image_path: Chart at trade close
            trade_result: Dictionary with P/L, outcome, etc.

        Returns:
            Learning insights
        """
        if not self.is_available():
            return {
                'success': False,
                'error': 'Claude Vision not available'
            }

        try:
            # Load both images
            setup_image = self._load_image(setup_image_path)
            outcome_image = self._load_image(outcome_image_path)

            if not setup_image or not outcome_image:
                return {
                    'success': False,
                    'error': 'Failed to load one or both images'
                }

            # Build learning prompt
            prompt = f"""
Analyze this trade from entry to outcome and provide learning insights.

Trade Result:
- Outcome: {trade_result.get('outcome', 'N/A')} (Win/Loss)
- P/L: {trade_result.get('pnl', 'N/A')}
- Duration: {trade_result.get('duration', 'N/A')}
- Exit Reason: {trade_result.get('exit_reason', 'N/A')}

First image: Trade setup at entry
Second image: Chart at trade close

Please analyze:
1. What worked well in this trade?
2. What could have been improved?
3. Were there any warning signs missed?
4. Key lessons from this trade
5. How to apply this learning to future trades
"""

            # Call with both images
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": setup_image['media_type'],
                                    "data": setup_image['base64']
                                }
                            },
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": outcome_image['media_type'],
                                    "data": outcome_image['base64']
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )

            return {
                'success': True,
                'learning_insights': response.content[0].text,
                'trade_result': trade_result,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Learning analysis failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _load_image(self, image_path: str) -> Optional[Dict[str, str]]:
        """
        Load and encode image for Claude Vision

        Args:
            image_path: Path to image file

        Returns:
            Dictionary with base64 data and media type, or None if failed
        """
        try:
            path = Path(image_path)

            if not path.exists():
                logger.error(f"Image not found: {image_path}")
                return None

            # Determine media type
            extension = path.suffix.lower()
            media_type_map = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.webp': 'image/webp',
                '.gif': 'image/gif'
            }

            media_type = media_type_map.get(extension, 'image/png')

            # Read and encode
            with open(path, 'rb') as f:
                image_bytes = f.read()
                base64_data = base64.standard_b64encode(image_bytes).decode('utf-8')

            return {
                'base64': base64_data,
                'media_type': media_type
            }

        except Exception as e:
            logger.error(f"Failed to load image {image_path}: {e}")
            return None

    def _build_analysis_prompt(
        self,
        analysis_type: str,
        context: Optional[Dict] = None
    ) -> str:
        """
        Build analysis prompt based on type and context

        Args:
            analysis_type: Type of analysis requested
            context: Optional context information

        Returns:
            Formatted prompt string
        """
        base_prompts = {
            'general': """
Analyze this trading chart and provide:
1. Current market structure (bullish/bearish/neutral)
2. Key support and resistance levels visible
3. Any patterns you can identify (order blocks, FVGs, liquidity zones)
4. Potential trading opportunities
5. Risk assessment
""",
            'pattern': """
Analyze this chart specifically for trading patterns:
1. Identify any order blocks (demand/supply zones)
2. Fair Value Gaps (FVGs)
3. Market structure shifts (MSS/CHoCH)
4. Liquidity sweeps (EQH/EQL)
5. W/M patterns
6. Support/Resistance levels
7. Premium/Discount zones

Be specific about locations and strengths.
""",
            'setup': """
Validate this potential trade setup from the chart:
1. Is the market structure favorable for this trade?
2. Are the identified levels valid?
3. Risk-reward ratio assessment
4. Entry quality (confluence factors)
5. Stop loss placement appropriateness
6. Target validity
7. Overall setup confidence level (Low/Medium/High)
8. Suggestions for improvement
""",
            'structure': """
Analyze market structure in this chart:
1. Overall trend direction
2. Higher timeframe structure
3. Lower timeframe structure
4. Recent breaks of structure
5. STL/STH levels
6. Trading range identification
7. Current phase (accumulation, markup, distribution, markdown)
"""
        }

        prompt = base_prompts.get(analysis_type, base_prompts['general'])

        # Add context if provided
        if context:
            if 'timeframe' in context:
                prompt = f"Chart Timeframe: {context['timeframe']}\n\n" + prompt

            if 'method' in context:
                prompt = f"Trading Method: {context['method']}\n\n" + prompt

        return prompt

    def batch_analyze_charts(
        self,
        image_paths: List[str],
        analysis_type: str = 'general'
    ) -> List[Dict[str, Any]]:
        """
        Analyze multiple charts in batch

        Args:
            image_paths: List of image file paths
            analysis_type: Type of analysis for all charts

        Returns:
            List of analysis results
        """
        results = []

        for image_path in image_paths:
            logger.info(f"Analyzing {image_path}...")
            result = self.analyze_chart_screenshot(image_path, analysis_type)
            results.append(result)

        logger.info(f"Batch analysis complete: {len(results)} charts analyzed")
        return results

    def save_analysis(
        self,
        analysis_result: Dict,
        output_dir: str = 'logs/vision_analysis'
    ) -> str:
        """
        Save analysis result to file

        Args:
            analysis_result: Analysis result dictionary
            output_dir: Directory to save results

        Returns:
            Path to saved file
        """
        try:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"analysis_{timestamp}.json"
            filepath = output_path / filename

            with open(filepath, 'w') as f:
                json.dump(analysis_result, f, indent=2)

            logger.info(f"Analysis saved to {filepath}")
            return str(filepath)

        except Exception as e:
            logger.error(f"Failed to save analysis: {e}")
            return ""


def test_claude_vision(image_path: str):
    """
    Test function to verify Claude Vision integration

    Args:
        image_path: Path to test chart image
    """
    analyzer = ClaudeVisionAnalyzer()

    if not analyzer.is_available():
        print("❌ Claude Vision not available")
        print("   - Check API key in config/.env")
        print("   - Ensure anthropic package is installed: pip install anthropic")
        return

    print("✅ Claude Vision is available")
    print(f"📊 Analyzing chart: {image_path}")

    result = analyzer.analyze_chart_screenshot(image_path, analysis_type='pattern')

    if result['success']:
        print("\n✅ Analysis completed successfully")
        print(f"\n{result['analysis']}")
        print(f"\nTokens used: {result['usage']['input_tokens']} input, {result['usage']['output_tokens']} output")
    else:
        print(f"\n❌ Analysis failed: {result.get('error', 'Unknown error')}")


if __name__ == '__main__':
    # Test with a sample chart if available
    test_chart = 'charts/test_chart.png'
    if Path(test_chart).exists():
        test_claude_vision(test_chart)
    else:
        print(f"Test chart not found: {test_chart}")
        print("Place a chart image at 'charts/test_chart.png' to test Claude Vision")
