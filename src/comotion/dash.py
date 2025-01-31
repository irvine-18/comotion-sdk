import io
import requests
import csv
from typing import Union, Callable
from os.path import join
import pandas as pd
import logging
from datetime import datetime
from tqdm import tqdm

def upload_csv_to_dash(
    dash_orgname: str,
    dash_api_key: str,
    dash_table: str,
    csv_gz_stream: io.FileIO
) -> requests.Response:
    """Uploads csv gzipped stream to Dash

    Expects a csv gzipped stream to upload to dash.

    Args:
        dash_orgname (str): Dash organisation name for dash instance
        dash_api_key (str): Valid API key for the organisation instance
        dash_table (str): Table name to upload to

        csv_gz_stream (io.FileIO): Description

    Returns:
        requests.Response: response from dash api

    Raises:
        HTTPError: If one is raised by the call
    """

    url = "https://api.comodash.io/v1/data-input-file"

    headers = {
        'Content-Type': 'application/gzip',
        'service_client_id': '0',
        'x-api-key': dash_api_key,
        'org-name': dash_orgname,
        'table-name': dash_table
    }

    dash_response = requests.request(
        "POST",
        url,
        headers=headers,
        data=csv_gz_stream.getbuffer()
    )

    dash_response.raise_for_status()

    return dash_response


def create_gzipped_csv_stream_from_df(df: pd.DataFrame) -> io.BytesIO:
    """Returns a gzipped, utf-8 csv file bytestream from a pandas dataframe

    Useful to help upload dataframes to dash

    It does not break file up, so be sure to apply a maximise chunksize
    to the dataframe before applying - otherwise dash max file limits will
    cause an error

    Parameters
    ----------
    df : pd.DataFrame
        Dateframe to be turned into bytestream

    Returns
    -------
    io.BytesIO
        The Bytestream

    """

    csv_stream = io.BytesIO()
    df.to_csv(
        csv_stream,
        compression="gzip",
        encoding="utf-8",
        index=False,
        quoting=csv.QUOTE_NONNUMERIC
    )

    return csv_stream


def read_and_upload_file_to_dash(
    file: Union[str, io.FileIO],
    dash_table: str,
    dash_orgname: str,
    dash_api_key: str,
    encoding: str = 'utf-8',
    chunksize: int = 30000,
    modify_lambda: Callable = None,
    path_to_output_for_dryrun: str = None
):
    """Reads a file and uploads to dash.

    This function will:
    - Read a csv file
    - Break it up into multiple csv's
    - each with a maximum number of lines defined by chunksize
    - upload them to dash

    Parameters
    ----------
    file : Union[str, io.FileIO]
        Either a path to the file to be uploaded,
        or a FileIO stream representing the file to be uploaded
        Should be an unencrypted, uncompressed CSV file
    dash_table: str
        name of Dash table to upload the file to
    dash_orgname: str
        orgname of your Dash instance
    dash_api_key: str
        valid api key for Dash API
    encoding: str
        the encoding of the source file.  defaults to utf-8.
    chunksize: int
        (optional)
        the maximum number of lines to be included in each file.
        Note that this should be low enough that the zipped file is less
        than Dash maximum gzipped file size. Defaults to 30000.
    modify_lambda:
        (optional)
        a callable that recieves the pandas dataframe read from the
        csv.  Gives the opportunity to modify - such as adding a timestamp
        column.
        Is not required.
    path_to_output_for_dryrun: str
        (optional)
        if specified, no upload will be made to dash, but files
        will be saved to the location specified. This is useful for
        testing.
        multiple files will be created: [table_name].[i].csv.gz where i
        represents multiple file parts

    Returns
    -------
    List
        List of http responses
    """
    file_reader = pd.read_csv(
        file,
        chunksize=chunksize,
        encoding=encoding
    )

    i = 1
    responses = []
    for file_df in file_reader:

        if modify_lambda is not None:
            modify_lambda(file_df)

        csv_stream = create_gzipped_csv_stream_from_df(file_df)

        if path_to_output_for_dryrun is None:

            response = upload_csv_to_dash(
                dash_orgname=dash_orgname,
                dash_api_key=dash_api_key,
                dash_table=dash_table,
                csv_gz_stream=csv_stream
            )

            responses.append(response.text)
        else:
            with open(
                join(
                    path_to_output_for_dryrun,
                    dash_table + "." + str(i) + ".csv.gz"
                ),
                "wb"
            ) as f:
                f.write(csv_stream.getvalue())

        i = i + 1

    return responses

def upload_dataframe(
    dataframe: pd.DataFrame,
    dash_table: str,
    dash_orgname: str,
    dash_api_key: str,
    dtypes: dict = None,
    chunksize: int = 30000,
    path_to_output_for_dryrun: str = None,
    include_snapshot: bool = True
):
    """Reads a file and uploads to dash.

    This function will:
    - Read a csv file
    - Break it up into multiple csv's
    - each with a maximum number of lines defined by chunksize
    - upload them to dash

    Parameters
    ----------
    file : pandas DataFrame object to be uploaded
    dash_table: str
        name of Dash table to upload the file to
    dash_orgname: str
        orgname of your Dash instance
    dash_api_key: str
        valid api key for Dash API
    dtypes: dict
        (optional)
        A dictionary that contains the column name and data type to convert to.
        Defaults to None i.e. load dataframe columns as they are
    chunksize: int
        (optional)
        the maximum number of lines to be included in each file.
        Note that this should be low enough that the zipped file is less
        than Dash maximum gzipped file size. Defaults to 30000.
    path_to_output_for_dryrun: str
        (optional)
        if specified, no upload will be made to dash, but files
        will be saved to the location specified. This is useful for
        testing.
        multiple files will be created: [table_name].[i].csv.gz where i
        represents multiple file parts
    include_snapshot: bool
        (optional)
        If True, an additional column 'snapshot_timestamp' will be added to the DataFrame.
        This column will contain the time that data is loaded in "%Y-%m-%d %H:%M:%S.%f" format in order to help with database management
        Defaults to True i.e. snapshot_timestamp is included

    Returns
    -------
    List
        List of http responses
    """

    snapshot_timestamp = datetime.now()

    log_file = dash_table + "_" + snapshot_timestamp.strftime("%Y%m%d%H%M") + ".log"

    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)-12s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d,%H:%M:%S'
    )

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Change columns format if dtypes is specified
    if dtypes:
        dataframe = dataframe.astype(dtype=dtypes)

    # Include snapshort time if include_snapshot == True
    if include_snapshot:
        dataframe['snapshot_timestamp'] = snapshot_timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")

    data_chunks = [dataframe[i:i+chunksize] for i in range(0, dataframe.shape[0], chunksize)]    
   
    for i, chunk in enumerate(tqdm(data_chunks)):

        csv_stream = create_gzipped_csv_stream_from_df(chunk)

        if path_to_output_for_dryrun is None:

            response = upload_csv_to_dash(
                dash_orgname=dash_orgname,
                dash_api_key=dash_api_key,
                dash_table=dash_table,
                csv_gz_stream=csv_stream
            )

            logger.info(response.text)

        else:
            with open(join(path_to_output_for_dryrun, dash_table + "." + str(i) + ".csv.gz"), "wb") as f:
                f.write(csv_stream.getvalue())

    return
