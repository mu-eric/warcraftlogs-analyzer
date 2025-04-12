import os
import httpx
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from dotenv import load_dotenv
import schemas
import logging

load_dotenv()

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # EXPLICITLY SET LEVEL
# Optional: Add a handler if running standalone, but Uvicorn should handle it
# handler = logging.StreamHandler()
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# handler.setFormatter(formatter)
# logger.addHandler(handler)

WCL_CLIENT_ID = os.getenv("WCL_CLIENT_ID")
WCL_CLIENT_SECRET = os.getenv("WCL_CLIENT_SECRET")
WCL_OAUTH_URL = "https://www.warcraftlogs.com/oauth/token"
WCL_API_V2_URL = "https://www.warcraftlogs.com/api/v2/client"

# Simple in-memory cache for the token
_token_cache = {
    "access_token": None,
    "expires_at": None
}

def is_token_valid():
    """Check if the cached token is still valid."""
    return _token_cache["access_token"] and \
           _token_cache["expires_at"] and \
           _token_cache["expires_at"] > datetime.now(timezone.utc)

async def get_access_token():
    """Get a valid access token, either from cache or by requesting a new one."""
    if is_token_valid():
        return _token_cache["access_token"]

    if not WCL_CLIENT_ID or not WCL_CLIENT_SECRET:
        raise ValueError("WCL_CLIENT_ID and WCL_CLIENT_SECRET must be set in .env file")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                WCL_OAUTH_URL,
                data={"grant_type": "client_credentials"},
                auth=(WCL_CLIENT_ID, WCL_CLIENT_SECRET)
            )
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            token_data = response.json()

            _token_cache["access_token"] = token_data["access_token"]
            expires_in = token_data["expires_in"] # seconds
            _token_cache["expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60) # Refresh a bit early

            print("Successfully obtained new WCL API token.") # Add logging
            return _token_cache["access_token"]
        except httpx.RequestError as exc:
            print(f"An error occurred while requesting {exc.request.url!r}: {exc}")
            raise
        except httpx.HTTPStatusError as exc:
            print(f"Error response {exc.response.status_code} while requesting {exc.request.url!r}: {exc.response.text}")
            raise

def extract_report_code(report_url: str) -> str | None:
    """Extracts the report code from a Warcraft Logs URL."""
    try:
        parsed_url = urlparse(report_url)
        path_parts = parsed_url.path.strip('/').split('/')
        # Expecting format like /reports/<code>
        if len(path_parts) >= 2 and path_parts[0] == 'reports':
            return path_parts[1]
    except Exception as e:
        print(f"Error parsing report URL '{report_url}': {e}")
    return None

async def fetch_fight_tables(report_code: str, fight_id: int) -> dict:
    """Fetches damage and healing tables for a specific fight ID."""
    graphql_query = """
    query FightTables($reportCode: String!, $fightIDs: [Int!]!) {
        reportData {
            report(code: $reportCode) {
                damageTable: table(dataType: DamageDone, fightIDs: $fightIDs)
                healingTable: table(dataType: Healing, fightIDs: $fightIDs)
            }
        }
    }
    """
    variables = {"reportCode": report_code, "fightIDs": [fight_id]}
    token = await get_access_token()
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                WCL_API_V2_URL,
                json={"query": graphql_query, "variables": variables},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logger.error(f"GraphQL error fetching fight tables for fight {fight_id}: {data['errors']}")
                return None

            report_data = data.get("data", {}).get("reportData", {}).get("report", {})
            logger.debug(f"WCL_SERVICE: Fetched tables for fight {fight_id}: {report_data}")
            return report_data

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching fight tables for fight {fight_id}: {e.response.status_code} - {e.response.text}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error fetching fight tables for fight {fight_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching fight tables for fight {fight_id}: {e}")
            return None


async def fetch_report_data(report_code: str) -> dict | None:
    logger.info(f"Fetching report data for {report_code}")
    token = await get_access_token()
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    variables = {"reportCode": report_code}

    report_info = None
    fights_raw = []
    master_data = {}
    all_events_combined = []

    # Create client ONCE to use for both calls
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Fetch metadata including fights and master data
        metadata_query = """
        query ReportMetadata($reportCode: String!) {
            reportData {
                report(code: $reportCode) {
                    code
                    title
                    startTime
                    endTime
                    zone { id name }
                    fights {
                        id
                        startTime
                        endTime
                        name
                        kill
                        difficulty
                        bossPercentage
                        averageItemLevel
                    }
                    masterData(translate: true) {
                        actors(type: "Player") {
                            id
                            name
                            subType
                            server
                        }
                        abilities {
                            gameID
                            name
                        }
                    }
                }
            }
        }
        """
        try:
            logger.info(f"Fetching metadata for report {report_code}")
            metadata_response = await client.post(
                WCL_API_V2_URL, # Use constant for V2 API
                json={"query": metadata_query, "variables": variables},
                headers=headers,
            )
            metadata_response.raise_for_status()
            report_data_root = metadata_response.json().get("data", {}).get("reportData", {})
            report_info = report_data_root.get("report", {})
            if not report_info:
                logger.error(f"No report found in metadata response for {report_code}")
                return None
            else:
                fights_raw = report_info.get("fights", [])
                master_data = report_info.get("masterData", {})
                logger.debug(f"WCL_SERVICE: Extracted metadata, {len(fights_raw)} fights, actors: {len(master_data.get('actors', []))}")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching metadata for {report_code}: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error fetching metadata for {report_code}: {e}", exc_info=True)
            return None

        # Extract necessary info for event query
        report_metadata = {
            "report_code": report_info.get("code"),
            "title": report_info.get("title"),
            "start_time_ms": report_info.get("startTime"),
            "end_time_ms": report_info.get("endTime"),
            "zone_id": report_info.get("zone", {}).get("id"),
            "zone_name": report_info.get("zone", {}).get("name"),
        }
        fight_ids = [f.get('id') for f in fights_raw if f.get('id') is not None]
        start_time = report_metadata['start_time_ms']
        end_time = report_metadata['end_time_ms']

        if not fight_ids or start_time is None or end_time is None:
            logger.warning(f"Missing data needed for event query (fights/times) for {report_code}. Skipping event fetch.")
        else:
            # Fetch events for ALL fights using the SAME client
            event_variables = {
                "reportCode": report_code,
                "fightIDs": fight_ids,
                "startTime": 0,
                "endTime": end_time - start_time,
                "limit": 10000
            }
            event_query = """
            query ReportEvents($reportCode: String!, $fightIDs: [Int], $startTime: Float!, $endTime: Float!, $limit: Int) {
                reportData {
                    report(code: $reportCode) {
                        events(fightIDs: $fightIDs, startTime: $startTime, endTime: $endTime, limit: $limit) {
                            data
                            nextPageTimestamp
                        }
                    }
                }
            }
            """
            try:
                logger.info(f"Fetching events for report {report_code}, fights: {fight_ids}")
                event_response = await client.post(
                    WCL_API_V2_URL, # Use constant for V2 API
                    json={"query": event_query, "variables": event_variables},
                    headers=headers,
                )
                event_response.raise_for_status()
                event_data_container = event_response.json().get("data", {}).get("reportData", {}).get("report", {}).get("events", {})
                all_events_combined = event_data_container.get("data", [])
                logger.info(f"Fetched {len(all_events_combined)} events for report {report_code}")
                # TODO: Implement pagination using nextPageTimestamp if necessary
            except httpx.HTTPStatusError as e:
                 logger.error(f"HTTP error fetching events for {report_code}: {e.response.status_code} - {e.response.text}")
                 # Continue without events, maybe?
            except Exception as e:
                logger.error(f"Error fetching events for report {report_code}: {e}", exc_info=True)
                # Continue without events

    # Process fights (outside the client block)
    processed_fights = [
        {
            "wcl_fight_id": fight.get("id"),
            "start_time_ms": fight.get("startTime"),
            "end_time_ms": fight.get("endTime"),
            "start_offset_ms": fight.get("startTime", 0) - report_metadata.get("start_time_ms", 0),
            "end_offset_ms": fight.get("endTime", 0) - report_metadata.get("start_time_ms", 0),
            "name": fight.get("name"),
            "kill": fight.get("kill"),
            "difficulty": fight.get("difficulty"),
            "boss_percentage": fight.get("bossPercentage"),
            "average_item_level": fight.get("averageItemLevel"),
        }
        for fight in fights_raw
    ]

    logger.info(f"Finished fetching data for {report_code}")
    return {
        "metadata": report_metadata,
        "fights": processed_fights,
        "master_data": master_data,
        "events": {"data": all_events_combined}
    }